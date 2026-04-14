#!/usr/bin/env node
// Tesslate AST Worker
// ─────────────────────────────────────────────────────────────────────
// Long-lived Node sidecar that performs JSX AST operations for the
// Tesslate Studio design view. Reads NDJSON commands from stdin, writes
// NDJSON replies to stdout.
//
// Protocol:
//   request : {"id": <int>, "op": "<op>", "payload": {...}}
//   reply   : {"id": <int>, "ok": true,  "result": {...}}
//           | {"id": <int>, "ok": false, "error": "<msg>"}
//
// Operations:
//   ping       → {"pong": true}
//   index      → inject data-oid into every JSX element, return oid→metadata
//   apply_diff → apply a list of CodeDiffRequest objects, return modified files

import { createInterface } from 'node:readline';
import { parse } from '@babel/parser';
import _traverse from '@babel/traverse';
import _generate from '@babel/generator';
import * as t from '@babel/types';
import { customAlphabet } from 'nanoid';
import { twMerge } from 'tailwind-merge';

const traverse = _traverse.default || _traverse;
const generate = _generate.default || _generate;

const OID_ATTR = 'data-oid';
const OID_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789';
const createOid = customAlphabet(OID_ALPHABET, 7);

// ── Parser ────────────────────────────────────────────────────────────
function parseSource(content) {
  return parse(content, {
    sourceType: 'module',
    allowImportExportEverywhere: true,
    allowReturnOutsideFunction: true,
    allowAwaitOutsideFunction: true,
    errorRecovery: true,
    plugins: [
      'jsx',
      'typescript',
      'decorators-legacy',
      'classProperties',
      'classPrivateProperties',
      'classPrivateMethods',
      'dynamicImport',
      'topLevelAwait',
      'optionalChaining',
      'nullishCoalescingOperator',
      'importMeta',
      'exportDefaultFrom',
    ],
  });
}

function regenerate(ast, source) {
  return generate(
    ast,
    { retainLines: true, retainFunctionParens: true, jsescOption: { minimal: true } },
    source,
  ).code;
}

// ── JSX attribute helpers ─────────────────────────────────────────────
function getAttrIndex(openingElement, name) {
  return openingElement.attributes.findIndex(
    (a) => a.type === 'JSXAttribute' && a.name && a.name.name === name,
  );
}

function getAttrValue(openingElement, name) {
  const idx = getAttrIndex(openingElement, name);
  if (idx < 0) return null;
  const attr = openingElement.attributes[idx];
  if (!attr.value) return null;
  if (attr.value.type === 'StringLiteral') return attr.value.value;
  if (
    attr.value.type === 'JSXExpressionContainer' &&
    attr.value.expression.type === 'StringLiteral'
  ) {
    return attr.value.expression.value;
  }
  return null;
}

function setStringAttr(openingElement, name, value) {
  const idx = getAttrIndex(openingElement, name);
  const attr = t.jsxAttribute(t.jsxIdentifier(name), t.stringLiteral(value));
  if (idx >= 0) openingElement.attributes[idx] = attr;
  else openingElement.attributes.push(attr);
}

function removeAttr(openingElement, name) {
  const idx = getAttrIndex(openingElement, name);
  if (idx >= 0) openingElement.attributes.splice(idx, 1);
}

function isFragment(openingElement) {
  const n = openingElement.name;
  if (!n) return true;
  if (n.type === 'JSXIdentifier' && n.name === 'Fragment') return true;
  if (
    n.type === 'JSXMemberExpression' &&
    n.object.type === 'JSXIdentifier' &&
    n.object.name === 'React' &&
    n.property.name === 'Fragment'
  ) {
    return true;
  }
  return false;
}

function getTagName(openingElement) {
  const n = openingElement.name;
  if (!n) return null;
  if (n.type === 'JSXIdentifier') return n.name;
  if (n.type === 'JSXMemberExpression') {
    const left = n.object.type === 'JSXIdentifier' ? n.object.name : '?';
    return `${left}.${n.property.name}`;
  }
  return null;
}

// ── Context detection (dynamic type, component name) ──────────────────
function detectDynamicType(path) {
  let p = path.parentPath;
  while (p) {
    if (p.isCallExpression && p.isCallExpression()) {
      const callee = p.node.callee;
      if (
        callee &&
        callee.type === 'MemberExpression' &&
        callee.property &&
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

function detectComponentName(path) {
  let p = path.parentPath;
  while (p) {
    const n = p.node;
    if (!n) break;
    if (n.type === 'FunctionDeclaration' && n.id) return n.id.name;
    if (n.type === 'ClassDeclaration' && n.id) return n.id.name;
    if (n.type === 'VariableDeclarator' && n.id && n.id.type === 'Identifier') {
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

// ══════════════════════════════════════════════════════════════════════
// OP: index
// ══════════════════════════════════════════════════════════════════════
function opIndex(payload) {
  const files = payload.files || [];
  const globalOids = new Set();
  const outFiles = [];
  const index = {};

  for (const file of files) {
    let ast;
    try {
      ast = parseSource(file.content);
    } catch (err) {
      outFiles.push({
        path: file.path,
        content: file.content,
        modified: false,
        error: String((err && err.message) || err),
      });
      continue;
    }

    let modified = false;
    const localOids = new Set();

    traverse(ast, {
      JSXOpeningElement(p) {
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
        index[oid] = {
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
        outFiles.push({
          path: file.path,
          content: file.content,
          modified: false,
          error: String((err && err.message) || err),
        });
        continue;
      }
    }
    outFiles.push({ path: file.path, content, modified });
  }

  return { files: outFiles, index };
}

// ══════════════════════════════════════════════════════════════════════
// OP: apply_diff
// ══════════════════════════════════════════════════════════════════════
function applyAttribute(openingElement, key, value, overrideClasses) {
  if (key === 'className' || key === 'class') {
    const existing = getAttrValue(openingElement, 'className') || '';
    let next;
    if (overrideClasses) {
      next = String(value || '').trim();
    } else {
      next = twMerge(existing, String(value || '')).trim();
    }
    if (next) setStringAttr(openingElement, 'className', next);
    else removeAttr(openingElement, 'className');
    return;
  }

  if (value === null || value === undefined) {
    removeAttr(openingElement, key);
    return;
  }

  const idx = getAttrIndex(openingElement, key);
  // Booleans: use shorthand (no value)
  const attrValue =
    typeof value === 'boolean' ? null : t.stringLiteral(String(value));
  const attr = t.jsxAttribute(t.jsxIdentifier(key), attrValue);
  if (idx >= 0) openingElement.attributes[idx] = attr;
  else openingElement.attributes.push(attr);
}

// Convert a CSS property name to its JSX camelCase equivalent.
// background-color → backgroundColor, -webkit-transform → WebkitTransform.
function cssPropToJsx(prop) {
  if (!prop) return prop;
  // Leading dash → capital letter (vendor prefixes)
  return prop
    .replace(/^-+/, (m) => m.slice(1).toUpperCase())
    .replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

// Merge a {cssProp: value} patch into the element's `style={{...}}` prop.
// Preserves any existing literal keys, overwrites colliding ones, and
// removes keys whose value in the patch is null/undefined/"".
function applyStylePatch(openingElement, patch) {
  const idx = getAttrIndex(openingElement, 'style');
  const newProps = {};

  // Load existing style object if it is a plain ObjectExpression with
  // literal keys. Anything more dynamic (spread, identifier, function call)
  // we leave untouched — we only know how to merge literal keys safely.
  let existingAttr = idx >= 0 ? openingElement.attributes[idx] : null;
  let preservedSpreads = [];
  if (
    existingAttr &&
    existingAttr.value &&
    existingAttr.value.type === 'JSXExpressionContainer' &&
    existingAttr.value.expression &&
    existingAttr.value.expression.type === 'ObjectExpression'
  ) {
    for (const prop of existingAttr.value.expression.properties) {
      if (prop.type === 'ObjectProperty' && prop.key) {
        const key =
          prop.key.type === 'Identifier'
            ? prop.key.name
            : prop.key.type === 'StringLiteral'
              ? prop.key.value
              : null;
        if (key !== null) newProps[key] = prop.value;
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

  const properties = [
    ...preservedSpreads,
    ...keys.map((k) => {
      const identKey = /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(k)
        ? t.identifier(k)
        : t.stringLiteral(k);
      return t.objectProperty(identKey, newProps[k]);
    }),
  ];
  const expr = t.objectExpression(properties);
  const attr = t.jsxAttribute(t.jsxIdentifier('style'), t.jsxExpressionContainer(expr));
  if (idx >= 0) openingElement.attributes[idx] = attr;
  else openingElement.attributes.push(attr);
}

function buildInsertElement(spec) {
  // spec = { tag_name, classes, text, oid, attributes, self_closing }
  const openingAttrs = [];
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

function applyStructureChange(jsxElement, change) {
  if (change.type === 'insert') {
    const el = buildInsertElement(change.element || {});
    const loc = change.location || 'append';
    if (loc === 'prepend') jsxElement.children.unshift(el);
    else if (typeof loc === 'number') jsxElement.children.splice(loc, 0, el);
    else jsxElement.children.push(el);
    return true;
  }
  return false;
}

function opApplyDiff(payload) {
  const files = payload.files || [];
  const requests = payload.requests || [];
  const byOid = new Map();
  for (const req of requests) {
    if (req && req.oid) byOid.set(req.oid, req);
  }

  const outFiles = [];
  for (const file of files) {
    let ast;
    try {
      ast = parseSource(file.content);
    } catch (err) {
      outFiles.push({
        path: file.path,
        content: file.content,
        modified: false,
        error: String((err && err.message) || err),
      });
      continue;
    }

    let modified = false;
    const elementsToRemove = [];

    traverse(ast, {
      JSXElement(p) {
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
          // Replace `<target>` with `<wrapper><target /></wrapper>`. The
          // inner target keeps all its props (including data-oid) via
          // cloneNode so any queued edits on it still apply in later
          // requests from the same batch.
          const tag = req.wrap_with.tag_name || 'div';
          const attrs = [];
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
          // Skip further traversal into the replaced subtree to avoid
          // double-processing the cloned inner element.
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
        outFiles.push({
          path: file.path,
          content: file.content,
          modified: false,
          error: String((err && err.message) || err),
        });
        continue;
      }
    }
    outFiles.push({ path: file.path, content, modified });
  }

  return { files: outFiles };
}

// ══════════════════════════════════════════════════════════════════════
// NDJSON driver
// ══════════════════════════════════════════════════════════════════════
const OPS = {
  ping: () => ({ pong: true, pid: process.pid }),
  index: opIndex,
  apply_diff: opApplyDiff,
};

function send(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

const rl = createInterface({ input: process.stdin, terminal: false });
rl.on('line', (line) => {
  if (!line) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch (err) {
    send({ id: null, ok: false, error: 'invalid_json: ' + String((err && err.message) || err) });
    return;
  }
  const id = msg.id ?? null;
  const op = msg.op;
  const payload = msg.payload || {};
  const fn = OPS[op];
  if (!fn) {
    send({ id, ok: false, error: 'unknown_op: ' + op });
    return;
  }
  try {
    const result = fn(payload);
    send({ id, ok: true, result });
  } catch (err) {
    send({
      id,
      ok: false,
      error: String((err && err.message) || err),
      stack: String((err && err.stack) || ''),
    });
  }
});

rl.on('close', () => process.exit(0));

// Signal ready so the parent can confirm startup without sending a ping.
send({ event: 'ready', pid: process.pid });
