import _traverseNs, { type NodePath, type Visitor } from '@babel/traverse';
import { twMerge } from 'tailwind-merge';
import * as t from '@babel/types';
import type { File as BabelFile, JSXElement, JSXOpeningElement, Node } from '@babel/types';

import {
  OID_ATTR,
  parseSource,
  regenerate,
  getAttrIndex,
  getAttrValue,
} from './common.js';
import type { FileInput } from '../budgets.js';

type TraverseFn = (ast: BabelFile | Node, visitor: Visitor) => void;
const traverse = (
  (_traverseNs as unknown as { default?: TraverseFn }).default ??
  (_traverseNs as unknown as TraverseFn)
) as TraverseFn;

export type AttrValue = string | number | boolean | null | undefined;

export interface InsertElementSpec {
  tag_name?: string;
  classes?: string;
  text?: string;
  oid?: string;
  attributes?: Record<string, AttrValue>;
  self_closing?: boolean;
}

export interface StructureChange {
  type: 'insert';
  location?: 'append' | 'prepend' | number;
  element?: InsertElementSpec;
}

export interface WrapSpec {
  tag_name?: string;
  oid?: string;
  classes?: string;
}

export interface DiffRequest {
  oid: string;
  attributes?: Record<string, AttrValue>;
  override_classes?: boolean;
  style_patch?: Record<string, AttrValue>;
  text_content?: string | null;
  structure_changes?: StructureChange[];
  wrap_with?: WrapSpec;
  remove?: boolean;
}

export interface ApplyDiffResult {
  path: string;
  content: string;
  modified: boolean;
  error?: string;
}

function setStringAttr(openingElement: JSXOpeningElement, name: string, value: string): void {
  const idx = getAttrIndex(openingElement, name);
  const attr = t.jsxAttribute(t.jsxIdentifier(name), t.stringLiteral(value));
  if (idx >= 0) openingElement.attributes[idx] = attr;
  else openingElement.attributes.push(attr);
}

function removeAttr(openingElement: JSXOpeningElement, name: string): void {
  const idx = getAttrIndex(openingElement, name);
  if (idx >= 0) openingElement.attributes.splice(idx, 1);
}

function applyAttribute(
  openingElement: JSXOpeningElement,
  key: string,
  value: AttrValue,
  overrideClasses: boolean,
): void {
  if (key === 'className' || key === 'class') {
    const existing = getAttrValue(openingElement, 'className') || '';
    const next = overrideClasses
      ? String(value || '').trim()
      : twMerge(existing, String(value || '')).trim();
    if (next) setStringAttr(openingElement, 'className', next);
    else removeAttr(openingElement, 'className');
    return;
  }

  if (value === null || value === undefined) {
    removeAttr(openingElement, key);
    return;
  }

  const idx = getAttrIndex(openingElement, key);
  const attrValue = typeof value === 'boolean' ? null : t.stringLiteral(String(value));
  const attr = t.jsxAttribute(t.jsxIdentifier(key), attrValue);
  if (idx >= 0) openingElement.attributes[idx] = attr;
  else openingElement.attributes.push(attr);
}

function cssPropToJsx(prop: string): string {
  return prop
    .replace(/^-+/, (m) => m.slice(1).toUpperCase())
    .replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
}

function applyStylePatch(openingElement: JSXOpeningElement, patch: Record<string, AttrValue>): void {
  const idx = getAttrIndex(openingElement, 'style');
  const newProps: Record<string, t.Expression> = {};
  const existingAttr = idx >= 0 ? openingElement.attributes[idx] : null;
  const preservedSpreads: t.SpreadElement[] = [];
  if (
    existingAttr &&
    existingAttr.type === 'JSXAttribute' &&
    existingAttr.value &&
    existingAttr.value.type === 'JSXExpressionContainer' &&
    existingAttr.value.expression.type === 'ObjectExpression'
  ) {
    for (const prop of existingAttr.value.expression.properties) {
      if (prop.type === 'ObjectProperty') {
        const key =
          prop.key.type === 'Identifier'
            ? prop.key.name
            : prop.key.type === 'StringLiteral'
              ? prop.key.value
              : null;
        if (key !== null && prop.value.type !== 'ArrayPattern' && prop.value.type !== 'ObjectPattern' && prop.value.type !== 'AssignmentPattern' && prop.value.type !== 'RestElement') {
          newProps[key] = prop.value as t.Expression;
        }
      } else if (prop.type === 'SpreadElement') {
        preservedSpreads.push(prop);
      }
    }
  }

  for (const [rawKey, rawValue] of Object.entries(patch)) {
    const key = cssPropToJsx(rawKey);
    if (rawValue === null || rawValue === undefined || rawValue === '') {
      delete newProps[key];
    } else {
      newProps[key] = t.stringLiteral(String(rawValue));
    }
  }

  const keys = Object.keys(newProps);
  if (keys.length === 0 && preservedSpreads.length === 0) {
    if (idx >= 0) openingElement.attributes.splice(idx, 1);
    return;
  }

  const properties: (t.ObjectProperty | t.SpreadElement)[] = [
    ...preservedSpreads,
    ...keys.map((k) => {
      const identKey = /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(k)
        ? t.identifier(k)
        : t.stringLiteral(k);
      return t.objectProperty(identKey, newProps[k]!);
    }),
  ];
  const expr = t.objectExpression(properties);
  const attr = t.jsxAttribute(t.jsxIdentifier('style'), t.jsxExpressionContainer(expr));
  if (idx >= 0) openingElement.attributes[idx] = attr;
  else openingElement.attributes.push(attr);
}

function buildInsertElement(spec: InsertElementSpec): JSXElement {
  const openingAttrs: t.JSXAttribute[] = [];
  if (spec.oid) {
    openingAttrs.push(t.jsxAttribute(t.jsxIdentifier(OID_ATTR), t.stringLiteral(spec.oid)));
  }
  if (spec.classes) {
    openingAttrs.push(t.jsxAttribute(t.jsxIdentifier('className'), t.stringLiteral(spec.classes)));
  }
  for (const [k, v] of Object.entries(spec.attributes || {})) {
    if (v === null || v === undefined) continue;
    openingAttrs.push(t.jsxAttribute(t.jsxIdentifier(k), t.stringLiteral(String(v))));
  }
  const tag = spec.tag_name || 'div';
  const selfClosing = !!spec.self_closing && !spec.text;
  const opening = t.jsxOpeningElement(t.jsxIdentifier(tag), openingAttrs, selfClosing);
  const closing = selfClosing ? null : t.jsxClosingElement(t.jsxIdentifier(tag));
  const children = spec.text ? [t.jsxText(String(spec.text))] : [];
  return t.jsxElement(opening, closing, children, selfClosing);
}

function applyStructureChange(jsxElement: JSXElement, change: StructureChange): boolean {
  if (change.type === 'insert') {
    const el = buildInsertElement(change.element || {});
    const loc = change.location ?? 'append';
    if (loc === 'prepend') jsxElement.children.unshift(el);
    else if (typeof loc === 'number') jsxElement.children.splice(loc, 0, el);
    else jsxElement.children.push(el);
    return true;
  }
  return false;
}

export function applyDiffFile(file: FileInput, byOid: Map<string, DiffRequest>): ApplyDiffResult {
  let ast;
  try {
    ast = parseSource(file.content);
  } catch (err) {
    return {
      path: file.path,
      content: file.content,
      modified: false,
      error: String((err as Error)?.message ?? err),
    };
  }

  let modified = false;
  const elementsToRemove: NodePath<JSXElement>[] = [];

  traverse(ast, {
    JSXElement(p: NodePath<JSXElement>) {
      const openingElement = p.node.openingElement;
      const oid = getAttrValue(openingElement, OID_ATTR);
      if (!oid) return;
      const req = byOid.get(oid);
      if (!req) return;

      if (req.remove) {
        elementsToRemove.push(p);
        return;
      }

      if (req.wrap_with && typeof req.wrap_with === 'object') {
        const tag = req.wrap_with.tag_name || 'div';
        const attrs: t.JSXAttribute[] = [];
        if (req.wrap_with.oid) {
          attrs.push(
            t.jsxAttribute(t.jsxIdentifier(OID_ATTR), t.stringLiteral(req.wrap_with.oid)),
          );
        }
        if (req.wrap_with.classes) {
          attrs.push(
            t.jsxAttribute(
              t.jsxIdentifier('className'),
              t.stringLiteral(req.wrap_with.classes),
            ),
          );
        }
        const opening = t.jsxOpeningElement(t.jsxIdentifier(tag), attrs, false);
        const closing = t.jsxClosingElement(t.jsxIdentifier(tag));
        const wrapper = t.jsxElement(opening, closing, [t.cloneNode(p.node, true)], false);
        p.replaceWith(wrapper);
        modified = true;
        p.skip();
        return;
      }

      if (req.attributes) {
        for (const [key, value] of Object.entries(req.attributes)) {
          applyAttribute(openingElement, key, value, !!req.override_classes);
          modified = true;
        }
      }

      if (req.style_patch && typeof req.style_patch === 'object') {
        applyStylePatch(openingElement, req.style_patch);
        modified = true;
      }

      if (req.text_content !== undefined && req.text_content !== null) {
        p.node.children = [t.jsxText(String(req.text_content))];
        modified = true;
      }

      if (req.structure_changes && req.structure_changes.length) {
        for (const change of req.structure_changes) {
          if (applyStructureChange(p.node, change)) modified = true;
        }
      }
    },
  });

  for (const path of elementsToRemove.reverse()) {
    path.remove();
    modified = true;
  }

  let content = file.content;
  if (modified) {
    try {
      content = regenerate(ast, file.content);
    } catch (err) {
      return {
        path: file.path,
        content: file.content,
        modified: false,
        error: String((err as Error)?.message ?? err),
      };
    }
  }

  return { path: file.path, content, modified };
}
