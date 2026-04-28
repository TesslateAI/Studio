/**
 * Bridge Installer — Writes the design bridge script into the user's project
 * and injects a <script> tag into the HTML entry point.
 *
 * Inspired by Onlook's approach: they write `builtwith.js` to `public/` and
 * add `<Script src="/builtwith.js">` to the Next.js layout. We do the same —
 * this completely sidesteps cross-origin iframe restrictions because the bridge
 * runs in the app's own context.
 *
 * Scope — frontend-framework projects only. detectEntryFile() looks for one of:
 *   - Next.js     → (src/)?app/layout.{tsx,jsx}
 *   - Vite/CRA/Vue/Svelte/Astro → root index.html
 *   - Angular     → src/index.html
 *   - Plain HTML  → any index.html
 * If none match (backend-only, native, mobile, etc.) install short-circuits
 * with a console warning and the project simply doesn't get the design bridge.
 */

import { projectsApi } from '../../../lib/api';
import type { FileTreeEntry } from '../../../utils/buildFileTree';
import { BRIDGE_SCRIPT_CONTENT } from './DesignBridge';

export const BRIDGE_FILENAME = '__tesslate-design-bridge.js';
const SCRIPT_TAG_MARKER = 'data-tesslate-design';
const SCRIPT_TAG = `<script src="/${BRIDGE_FILENAME}" ${SCRIPT_TAG_MARKER}></script>`;
const SCRIPT_TAG_REGEX = /<script[^>]*data-tesslate-design[^>]*><\/script>\s*/g;

// ── Entry file detection ──────────────────────────────────────────────

interface EntryFileInfo {
  path: string;
  framework: 'nextjs' | 'vite' | 'cra' | 'vue' | 'svelte' | 'angular' | 'astro' | 'html';
  injectBefore: string; // regex/string to inject the script tag before
}

/**
 * Detect the project's HTML entry file from the file tree.
 * Returns the path and framework info, or null if not detectable.
 */
export function detectEntryFile(fileTree: FileTreeEntry[]): EntryFileInfo | null {
  const paths = new Set(fileTree.map(f => f.path));
  const hasPath = (p: string) => paths.has(p);

  // Next.js — layout.tsx in app/ or src/app/
  for (const layoutPath of [
    'src/app/layout.tsx',
    'src/app/layout.jsx',
    'app/layout.tsx',
    'app/layout.jsx',
  ]) {
    if (hasPath(layoutPath)) {
      return { path: layoutPath, framework: 'nextjs', injectBefore: '</body>' };
    }
  }

  // Vite / CRA / Vue / Svelte / Astro — index.html at root or public/
  for (const htmlPath of ['index.html', 'public/index.html']) {
    if (hasPath(htmlPath)) {
      // Distinguish framework from other markers
      const framework = detectFrameworkFromTree(fileTree);
      return { path: htmlPath, framework, injectBefore: '</body>' };
    }
  }

  // Angular — src/index.html
  if (hasPath('src/index.html')) {
    return { path: 'src/index.html', framework: 'angular', injectBefore: '</body>' };
  }

  return null;
}

function detectFrameworkFromTree(fileTree: FileTreeEntry[]): EntryFileInfo['framework'] {
  const paths = fileTree.map(f => f.path.toLowerCase());
  const has = (pattern: string) => paths.some(p => p.includes(pattern));

  if (has('vite.config') || has('vite.config.ts') || has('vite.config.js')) return 'vite';
  if (has('vue.config') || paths.some(p => p.endsWith('.vue'))) return 'vue';
  if (has('svelte.config') || paths.some(p => p.endsWith('.svelte'))) return 'svelte';
  if (has('astro.config')) return 'astro';
  if (has('angular.json')) return 'angular';
  if (has('react-scripts') || has('react-app-env')) return 'cra';
  return 'vite'; // default for generic projects with index.html
}

// ── Public dir detection ──────────────────────────────────────────────

function detectPublicDir(fileTree: FileTreeEntry[]): string {
  const paths = new Set(fileTree.filter(f => f.is_dir).map(f => f.path));
  if (paths.has('public')) return 'public';
  if (paths.has('static')) return 'static';
  // For Next.js or Vite, public/ is standard — create it even if not in tree
  return 'public';
}

// ── Install bridge ────────────────────────────────────────────────────

/**
 * Install the design bridge into the user's project:
 * 1. Write the bridge script to public/__tesslate-design-bridge.js
 * 2. Inject a <script> tag into the HTML entry file
 *
 * Returns true if successful.
 */
export async function installBridge(
  slug: string,
  fileTree: FileTreeEntry[],
  containerDir?: string,
): Promise<boolean> {
  try {
    const entry = detectEntryFile(fileTree);
    if (!entry) {
      console.warn('[DesignBridge] Could not detect entry file — bridge not installed');
      return false;
    }

    const publicDir = detectPublicDir(fileTree);
    const bridgePath = `${publicDir}/${BRIDGE_FILENAME}`;

    // 1. Write bridge script to public dir
    await projectsApi.saveFile(slug, bridgePath, BRIDGE_SCRIPT_CONTENT);

    // 2. Read the entry file
    const entryResponse = await projectsApi.getFileContent(slug, entry.path, containerDir);
    const entryContent = typeof entryResponse === 'string' ? entryResponse : entryResponse?.content;
    if (!entryContent) {
      console.warn('[DesignBridge] Could not read entry file:', entry.path);
      return false;
    }

    // Check if already injected
    if (entryContent.includes(SCRIPT_TAG_MARKER)) {
      return true; // Already installed
    }

    // 3. Inject script tag
    let modifiedContent: string;

    if (entry.framework === 'nextjs') {
      // Next.js: inject before </body> in JSX
      modifiedContent = injectIntoNextJsLayout(entryContent);
    } else {
      // HTML files: inject before </body>
      modifiedContent = injectIntoHtml(entryContent);
    }

    if (modifiedContent === entryContent) {
      console.warn('[DesignBridge] Could not find injection point in', entry.path);
      return false;
    }

    await projectsApi.saveFile(slug, entry.path, modifiedContent);
    return true;
  } catch (err) {
    console.error('[DesignBridge] Install failed:', err);
    return false;
  }
}

/**
 * Inject script tag into a standard HTML file (before </body>)
 */
function injectIntoHtml(content: string): string {
  const bodyCloseIdx = content.lastIndexOf('</body>');
  if (bodyCloseIdx === -1) {
    // No </body> — try appending before </html>
    const htmlCloseIdx = content.lastIndexOf('</html>');
    if (htmlCloseIdx === -1) {
      // Last resort: append to end
      return content + '\n' + SCRIPT_TAG + '\n';
    }
    return content.slice(0, htmlCloseIdx) + '  ' + SCRIPT_TAG + '\n' + content.slice(htmlCloseIdx);
  }
  return content.slice(0, bodyCloseIdx) + '  ' + SCRIPT_TAG + '\n  ' + content.slice(bodyCloseIdx);
}

/**
 * Inject Script component into a Next.js layout.tsx file.
 * Raw <script> tags in JSX don't execute — must use next/script's <Script> component.
 * Adds the import at the top and the <Script> component before </body>.
 */
function injectIntoNextJsLayout(content: string): string {
  const bodyCloseRegex = /<\/body\s*>/;
  const match = bodyCloseRegex.exec(content);
  if (!match) return content;

  // Add next/script import if not already present
  let result = content;
  if (!result.includes('next/script')) {
    // Insert import after the last import statement
    const lastImportIdx = result.lastIndexOf('\nimport ');
    if (lastImportIdx !== -1) {
      const lineEnd = result.indexOf('\n', lastImportIdx + 1);
      result = result.slice(0, lineEnd + 1) +
        `import Script from "next/script";\n` +
        result.slice(lineEnd + 1);
    } else {
      // No imports found — add at top
      result = `import Script from "next/script";\n` + result;
    }
  }

  // Insert <Script> component before </body>
  const bodyMatch = bodyCloseRegex.exec(result);
  if (!bodyMatch) return content;
  const insertPos = bodyMatch.index;
  const scriptJsx = `<Script src="/${BRIDGE_FILENAME}" strategy="afterInteractive" data-tesslate-design />`;
  return result.slice(0, insertPos) + scriptJsx + result.slice(insertPos);
}

// ── Uninstall bridge ──────────────────────────────────────────────────

/**
 * Remove the design bridge from the user's project:
 * 1. Remove the script tag from the entry HTML
 * 2. Delete the bridge script file
 */
export async function uninstallBridge(
  slug: string,
  fileTree: FileTreeEntry[],
  containerDir?: string,
): Promise<void> {
  try {
    const entry = detectEntryFile(fileTree);
    const publicDir = detectPublicDir(fileTree);
    const bridgePath = `${publicDir}/${BRIDGE_FILENAME}`;

    // 1. Remove script tag from entry file
    if (entry) {
      try {
        const entryResponse = await projectsApi.getFileContent(slug, entry.path, containerDir);
        const entryContent = typeof entryResponse === 'string' ? entryResponse : entryResponse?.content;
        if (entryContent && entryContent.includes(SCRIPT_TAG_MARKER)) {
          let cleaned = entryContent;
          // Remove HTML-style script tag
          cleaned = cleaned.replace(SCRIPT_TAG_REGEX, '');
          // Remove JSX-style <script> tag (self-closing)
          cleaned = cleaned.replace(/<script\s+src="[^"]*__tesslate-design-bridge\.js"[^/]*\/>\s*/g, '');
          // Remove Next.js <Script> component tag
          cleaned = cleaned.replace(/<Script\s+src="[^"]*__tesslate-design-bridge\.js"[^/]*\/>\s*/g, '');
          // Remove the import if we added it
          cleaned = cleaned.replace(/import Script from ["']next\/script["'];\n?/g, '');
          // Clean up extra blank lines
          cleaned = cleaned.replace(/\n\s*\n\s*\n/g, '\n\n');

          if (cleaned !== entryContent) {
            await projectsApi.saveFile(slug, entry.path, cleaned);
          }
        }
      } catch {
        // Entry file may not exist or be readable — that's OK
      }
    }

    // 2. Delete bridge script file
    try {
      await projectsApi.deleteFile(slug, bridgePath);
    } catch {
      // File may not exist — that's OK
    }
  } catch (err) {
    console.warn('[DesignBridge] Uninstall error (non-fatal):', err);
  }
}

// ── Check if bridge is installed ──────────────────────────────────────

/**
 * Check if the bridge script file exists in the project's public directory.
 */
export function isBridgeInstalled(fileTree: FileTreeEntry[]): boolean {
  const publicDir = detectPublicDir(fileTree);
  const bridgePath = `${publicDir}/${BRIDGE_FILENAME}`;
  return fileTree.some(f => f.path === bridgePath);
}
