import _traverseNs, { type NodePath, type Visitor } from '@babel/traverse';
import { customAlphabet } from 'nanoid';
import * as t from '@babel/types';
import type { File as BabelFile, JSXOpeningElement, Node } from '@babel/types';

import {
  OID_ATTR,
  parseSource,
  regenerate,
  getAttrIndex,
  getAttrValue,
  isFragment,
  getTagName,
} from './common.js';
import type { FileInput } from '../budgets.js';

type TraverseFn = (ast: BabelFile | Node, visitor: Visitor) => void;
const traverse = (
  (_traverseNs as unknown as { default?: TraverseFn }).default ??
  (_traverseNs as unknown as TraverseFn)
) as TraverseFn;

const OID_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789';
const createOid = customAlphabet(OID_ALPHABET, 7);

export interface OidMeta {
  path: string;
  tag_name: string;
  start_line: number | null;
  start_col: number | null;
  end_line: number | null;
  end_col: number | null;
  component: string | null;
  dynamic_type: 'array' | 'conditional' | null;
}

export interface IndexFileResult {
  path: string;
  content: string;
  modified: boolean;
  error?: string;
  index: Record<string, OidMeta>;
}

function setStringAttr(openingElement: JSXOpeningElement, name: string, value: string): void {
  const idx = getAttrIndex(openingElement, name);
  const attr = t.jsxAttribute(t.jsxIdentifier(name), t.stringLiteral(value));
  if (idx >= 0) openingElement.attributes[idx] = attr;
  else openingElement.attributes.push(attr);
}

function detectDynamicType(path: NodePath): OidMeta['dynamic_type'] {
  let p: NodePath | null = path.parentPath;
  while (p) {
    if (p.isCallExpression && p.isCallExpression()) {
      const callee = p.node.callee;
      if (
        callee &&
        callee.type === 'MemberExpression' &&
        callee.property.type === 'Identifier' &&
        callee.property.name === 'map'
      ) {
        return 'array';
      }
    }
    if (p.isConditionalExpression && p.isConditionalExpression()) return 'conditional';
    if (
      p.isLogicalExpression &&
      p.isLogicalExpression() &&
      (p.node.operator === '&&' || p.node.operator === '||')
    ) {
      return 'conditional';
    }
    p = p.parentPath;
  }
  return null;
}

function detectComponentName(path: NodePath): string | null {
  let p: NodePath | null = path.parentPath;
  while (p) {
    const n = p.node;
    if (!n) break;
    if (n.type === 'FunctionDeclaration' && n.id) return n.id.name;
    if (n.type === 'ClassDeclaration' && n.id) return n.id.name;
    if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier') {
      if (
        n.init &&
        (n.init.type === 'ArrowFunctionExpression' || n.init.type === 'FunctionExpression')
      ) {
        return n.id.name;
      }
    }
    p = p.parentPath;
  }
  return null;
}

// Inject data-oid into every JSX element in one file. Idempotent:
// already-oid'd elements keep their existing ids.
export function indexFile(file: FileInput, globalOids: Set<string>): IndexFileResult {
  let ast;
  try {
    ast = parseSource(file.content);
  } catch (err) {
    return {
      path: file.path,
      content: file.content,
      modified: false,
      error: String((err as Error)?.message ?? err),
      index: {},
    };
  }

  let modified = false;
  const localOids = new Set<string>();
  const fileIndex: Record<string, OidMeta> = {};

  traverse(ast, {
    JSXOpeningElement(p: NodePath<JSXOpeningElement>) {
      if (isFragment(p.node)) return;
      const tagName = getTagName(p.node);
      if (!tagName) return;

      let oid = getAttrValue(p.node, OID_ATTR);
      if (!oid || localOids.has(oid) || globalOids.has(oid)) {
        do {
          oid = createOid();
        } while (globalOids.has(oid) || localOids.has(oid));
        setStringAttr(p.node, OID_ATTR, oid);
        modified = true;
      }
      localOids.add(oid);
      globalOids.add(oid);

      const loc = p.node.loc;
      fileIndex[oid] = {
        path: file.path,
        tag_name: tagName,
        start_line: loc ? loc.start.line : null,
        start_col: loc ? loc.start.column : null,
        end_line: loc ? loc.end.line : null,
        end_col: loc ? loc.end.column : null,
        component: detectComponentName(p),
        dynamic_type: detectDynamicType(p),
      };
    },
  });

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
        index: {},
      };
    }
  }

  return { path: file.path, content, modified, index: fileIndex };
}
