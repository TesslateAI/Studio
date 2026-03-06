/**
 * SEO Manager - Tag Registry Pattern
 *
 * Manages document head meta tags with proper cleanup on navigation.
 * Tracks which tags were dynamically added vs existed in HTML,
 * and restores original values on cleanup.
 *
 * Features:
 * - Prevents duplicate meta tags
 * - Restores original tag values on cleanup
 * - Removes dynamically added tags on unmount
 * - Singleton pattern for consistent state
 */

// =============================================================================
// Types
// =============================================================================

interface TagEntry {
  /** Original value before we modified it (null if tag didn't exist) */
  original: string | null;
  /** Whether this tag is currently managed by SEOManager */
  managed: boolean;
}

interface SEOTagRegistry {
  /** Meta tags by name/property key */
  meta: Map<string, TagEntry>;
  /** Link tags (canonical, etc.) by rel attribute */
  links: Map<string, TagEntry>;
  /** Script tags (structured data) */
  scripts: Set<Element>;
}

// =============================================================================
// SEO Manager Class
// =============================================================================

class SEOManager {
  private static instance: SEOManager | null = null;
  private registry: SEOTagRegistry;
  private originalTitle: string;

  private constructor() {
    this.registry = {
      meta: new Map(),
      links: new Map(),
      scripts: new Set(),
    };
    this.originalTitle =
      typeof document !== 'undefined' ? document.title : 'Tesslate';
  }

  /**
   * Get singleton instance
   */
  static getInstance(): SEOManager {
    if (!SEOManager.instance) {
      SEOManager.instance = new SEOManager();
    }
    return SEOManager.instance;
  }

  /**
   * Set a meta tag value, tracking original for cleanup
   *
   * @param key - The meta name or property
   * @param value - The content value
   * @param isProperty - If true, use property attribute instead of name
   */
  setMeta(key: string, value: string, isProperty = false): void {
    if (typeof document === 'undefined') return;

    const attr = isProperty ? 'property' : 'name';
    const selector = `meta[${attr}="${key}"]`;
    let meta = document.querySelector<HTMLMetaElement>(selector);

    // Track original value on first touch
    if (!this.registry.meta.has(key)) {
      this.registry.meta.set(key, {
        original: meta?.content || null,
        managed: true,
      });
    }

    // Create tag if doesn't exist
    if (!meta) {
      meta = document.createElement('meta');
      meta.setAttribute(attr, key);
      document.head.appendChild(meta);
    }

    // Update content
    meta.content = value;
  }

  /**
   * Remove/restore a meta tag to its original state
   *
   * @param key - The meta name or property
   * @param isProperty - If true, use property attribute instead of name
   */
  removeMeta(key: string, isProperty = false): void {
    if (typeof document === 'undefined') return;

    const entry = this.registry.meta.get(key);
    if (!entry) return;

    const attr = isProperty ? 'property' : 'name';
    const meta = document.querySelector<HTMLMetaElement>(
      `meta[${attr}="${key}"]`
    );

    if (entry.original !== null) {
      // Restore original value
      if (meta) meta.content = entry.original;
    } else if (meta) {
      // Remove tag that didn't exist originally
      meta.remove();
    }

    this.registry.meta.delete(key);
  }

  /**
   * Set a link tag (e.g., canonical URL)
   *
   * @param rel - The rel attribute value
   * @param href - The href value
   */
  setLink(rel: string, href: string): void {
    if (typeof document === 'undefined') return;

    let link = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);

    // Track original value on first touch
    if (!this.registry.links.has(rel)) {
      this.registry.links.set(rel, {
        original: link?.href || null,
        managed: true,
      });
    }

    // Create link if doesn't exist
    if (!link) {
      link = document.createElement('link');
      link.rel = rel;
      document.head.appendChild(link);
    }

    link.href = href;
  }

  /**
   * Remove/restore a link tag to its original state
   */
  removeLink(rel: string): void {
    if (typeof document === 'undefined') return;

    const entry = this.registry.links.get(rel);
    if (!entry) return;

    const link = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);

    if (entry.original !== null) {
      if (link) link.href = entry.original;
    } else if (link) {
      link.remove();
    }

    this.registry.links.delete(rel);
  }

  /**
   * Set document title, tracking original for cleanup
   */
  setTitle(title: string): void {
    if (typeof document === 'undefined') return;
    document.title = title;
  }

  /**
   * Restore original document title
   */
  restoreTitle(): void {
    if (typeof document === 'undefined') return;
    document.title = this.originalTitle;
  }

  /**
   * Add JSON-LD structured data script
   *
   * @param data - The structured data object
   * @param id - Optional ID for the script tag
   */
  setStructuredData(data: Record<string, unknown>, id = 'seo-structured-data'): void {
    if (typeof document === 'undefined') return;

    // Remove existing script with same ID
    const existing = document.querySelector(`script[data-seo="${id}"]`);
    if (existing) {
      this.registry.scripts.delete(existing);
      existing.remove();
    }

    // Create new script
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.setAttribute('data-seo', id);
    script.textContent = JSON.stringify(data);
    document.head.appendChild(script);

    this.registry.scripts.add(script);
  }

  /**
   * Remove a structured data script by ID
   */
  removeStructuredData(id = 'seo-structured-data'): void {
    if (typeof document === 'undefined') return;

    const script = document.querySelector(`script[data-seo="${id}"]`);
    if (script) {
      this.registry.scripts.delete(script);
      script.remove();
    }
  }

  /**
   * Get list of currently managed meta tag keys
   */
  getManagedMetaKeys(): string[] {
    return Array.from(this.registry.meta.keys());
  }

  /**
   * Cleanup all managed tags and restore originals
   * Call this on component unmount or route change
   */
  cleanup(): void {
    if (typeof document === 'undefined') return;

    // Restore all meta tags
    this.registry.meta.forEach((_entry, key) => {
      // Determine if property or name based on key prefix
      const isProperty = key.startsWith('og:') || key.startsWith('article:');
      this.removeMeta(key, isProperty);
    });

    // Restore all link tags
    this.registry.links.forEach((_, rel) => {
      this.removeLink(rel);
    });

    // Remove all structured data scripts
    this.registry.scripts.forEach((script) => script.remove());
    this.registry.scripts.clear();

    // Restore original title
    this.restoreTitle();
  }

  /**
   * Cleanup specific tags by keys
   * Useful for component-specific cleanup without affecting global tags
   */
  cleanupKeys(keys: string[]): void {
    if (typeof document === 'undefined') return;

    keys.forEach((key) => {
      const isProperty = key.startsWith('og:') || key.startsWith('article:');
      this.removeMeta(key, isProperty);
    });
  }
}

// =============================================================================
// Exports
// =============================================================================

/**
 * Get the singleton SEO Manager instance
 */
export function getSEOManager(): SEOManager {
  return SEOManager.getInstance();
}

/**
 * Convenience function to set common meta tags
 */
export function setPageSEO(options: {
  title: string;
  description: string;
  url?: string;
  image?: string;
  type?: 'website' | 'article' | 'product';
  author?: string;
  keywords?: string[];
}): string[] {
  const manager = getSEOManager();
  const managedKeys: string[] = [];

  const fullTitle = options.title.includes('Tesslate')
    ? options.title
    : `${options.title} | Tesslate`;

  manager.setTitle(fullTitle);

  // Basic meta
  manager.setMeta('description', options.description);
  managedKeys.push('description');

  if (options.keywords?.length) {
    manager.setMeta('keywords', options.keywords.join(', '));
    managedKeys.push('keywords');
  }

  if (options.author) {
    manager.setMeta('author', options.author);
    managedKeys.push('author');
  }

  // Open Graph
  manager.setMeta('og:title', fullTitle, true);
  manager.setMeta('og:description', options.description, true);
  manager.setMeta('og:type', options.type || 'website', true);
  manager.setMeta('og:site_name', 'Tesslate', true);
  managedKeys.push('og:title', 'og:description', 'og:type', 'og:site_name');

  if (options.url) {
    manager.setMeta('og:url', options.url, true);
    manager.setLink('canonical', options.url);
    managedKeys.push('og:url');
  }

  if (options.image) {
    manager.setMeta('og:image', options.image, true);
    manager.setMeta('og:image:alt', options.title, true);
    managedKeys.push('og:image', 'og:image:alt');
  }

  // Twitter
  manager.setMeta('twitter:card', options.image ? 'summary_large_image' : 'summary');
  manager.setMeta('twitter:title', fullTitle);
  manager.setMeta('twitter:description', options.description);
  managedKeys.push('twitter:card', 'twitter:title', 'twitter:description');

  if (options.image) {
    manager.setMeta('twitter:image', options.image);
    managedKeys.push('twitter:image');
  }

  return managedKeys;
}

/**
 * Cleanup specific keys from SEO
 */
export function cleanupPageSEO(keys: string[]): void {
  getSEOManager().cleanupKeys(keys);
}

export { SEOManager };
export default getSEOManager;
