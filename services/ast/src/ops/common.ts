import { parse, type ParserPlugin } from '@babel/parser';
import _generateNs from '@babel/generator';
import type { File, JSXOpeningElement } from '@babel/types';

// @babel/generator ships as CJS; under esModuleInterop the "default
// import" can be either the namespace or the function depending on
// interop flavor. Normalize.
const generate = (
  (_generateNs as unknown as { default?: (...args: unknown[]) => { code: string } }).default ??
  (_generateNs as unknown as (...args: unknown[]) => { code: string })
) as (ast: File, opts: object, source: string) => { code: string };

export const OID_ATTR = 'data-oid';

const PARSER_PLUGINS: ParserPlugin[] = [
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
];

export function parseSource(content: string): File {
  return parse(content, {
    sourceType: 'module',
    allowImportExportEverywhere: true,
    allowReturnOutsideFunction: true,
    allowAwaitOutsideFunction: true,
    errorRecovery: true,
    plugins: PARSER_PLUGINS,
  });
}

export function regenerate(ast: File, source: string): string {
  return generate(
    ast,
    { retainLines: true, retainFunctionParens: true, jsescOption: { minimal: true } },
    source,
  ).code;
}

// ── JSX attribute helpers ─────────────────────────────────────────────
export function getAttrIndex(openingElement: JSXOpeningElement, name: string): number {
  return openingElement.attributes.findIndex(
    (a) => a.type === 'JSXAttribute' && a.name && (a.name as { name?: string }).name === name,
  );
}

export function getAttrValue(openingElement: JSXOpeningElement, name: string): string | null {
  const idx = getAttrIndex(openingElement, name);
  if (idx < 0) return null;
  const attr = openingElement.attributes[idx];
  if (!attr || attr.type !== 'JSXAttribute' || !attr.value) return null;
  if (attr.value.type === 'StringLiteral') return attr.value.value;
  if (
    attr.value.type === 'JSXExpressionContainer' &&
    attr.value.expression.type === 'StringLiteral'
  ) {
    return attr.value.expression.value;
  }
  return null;
}

export function isFragment(openingElement: JSXOpeningElement): boolean {
  const n = openingElement.name;
  if (!n) return true;
  if (n.type === 'JSXIdentifier' && n.name === 'Fragment') return true;
  if (
    n.type === 'JSXMemberExpression' &&
    n.object.type === 'JSXIdentifier' &&
    n.object.name === 'React' &&
    n.property.type === 'JSXIdentifier' &&
    n.property.name === 'Fragment'
  ) {
    return true;
  }
  return false;
}

export function getTagName(openingElement: JSXOpeningElement): string | null {
  const n = openingElement.name;
  if (!n) return null;
  if (n.type === 'JSXIdentifier') return n.name;
  if (n.type === 'JSXMemberExpression') {
    const left = n.object.type === 'JSXIdentifier' ? n.object.name : '?';
    const right = n.property.type === 'JSXIdentifier' ? n.property.name : '?';
    return `${left}.${right}`;
  }
  return null;
}
