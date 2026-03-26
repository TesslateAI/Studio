import { useEffect, useRef } from 'react';
import { getSEOManager } from '../lib/seo-manager';

interface SEOProps {
  title: string;
  description: string;
  keywords?: string[];
  image?: string;
  url?: string;
  type?: 'website' | 'article' | 'product';
  author?: string;
  publishedTime?: string;
  modifiedTime?: string;
  // Structured data for rich snippets
  structuredData?: Record<string, unknown>;
}

/**
 * SEO Component - Manages document head meta tags for search engine optimization
 * Updates title, meta description, Open Graph, Twitter Cards, and JSON-LD structured data
 *
 * Uses SEOManager for proper tag tracking and cleanup to prevent duplicate tags
 * on navigation between routes.
 */
export function SEO({
  title,
  description,
  keywords = [],
  image,
  url,
  type = 'website',
  author,
  publishedTime,
  modifiedTime,
  structuredData,
}: SEOProps) {
  // Track which keys we manage so we can clean them up
  const managedKeysRef = useRef<string[]>([]);

  useEffect(() => {
    const manager = getSEOManager();
    const managedKeys: string[] = [];

    // Update document title
    const fullTitle = title.includes('Tesslate') ? title : `${title} | Tesslate Marketplace`;
    manager.setTitle(fullTitle);

    // Basic meta tags
    manager.setMeta('description', description);
    managedKeys.push('description');

    if (keywords.length > 0) {
      manager.setMeta('keywords', keywords.join(', '));
      managedKeys.push('keywords');
    }

    if (author) {
      manager.setMeta('author', author);
      managedKeys.push('author');
    }

    // Open Graph tags (for Facebook, LinkedIn, etc.)
    manager.setMeta('og:title', fullTitle, true);
    manager.setMeta('og:description', description, true);
    manager.setMeta('og:type', type, true);
    manager.setMeta('og:site_name', 'Tesslate Marketplace', true);
    managedKeys.push('og:title', 'og:description', 'og:type', 'og:site_name');

    if (url) {
      manager.setMeta('og:url', url, true);
      manager.setLink('canonical', url);
      managedKeys.push('og:url');
    }

    if (image) {
      manager.setMeta('og:image', image, true);
      manager.setMeta('og:image:alt', title, true);
      managedKeys.push('og:image', 'og:image:alt');
    }

    // Twitter Card tags
    manager.setMeta('twitter:card', image ? 'summary_large_image' : 'summary');
    manager.setMeta('twitter:title', fullTitle);
    manager.setMeta('twitter:description', description);
    managedKeys.push('twitter:card', 'twitter:title', 'twitter:description');

    if (image) {
      manager.setMeta('twitter:image', image);
      managedKeys.push('twitter:image');
    }

    // Article specific tags
    if (type === 'article') {
      if (publishedTime) {
        manager.setMeta('article:published_time', publishedTime, true);
        managedKeys.push('article:published_time');
      }
      if (modifiedTime) {
        manager.setMeta('article:modified_time', modifiedTime, true);
        managedKeys.push('article:modified_time');
      }
      if (author) {
        manager.setMeta('article:author', author, true);
        managedKeys.push('article:author');
      }
    }

    // JSON-LD Structured Data
    if (structuredData) {
      manager.setStructuredData(structuredData, 'structured-data');
    }

    // Store for cleanup
    managedKeysRef.current = managedKeys;

    // Cleanup on unmount - restore original values or remove added tags
    return () => {
      manager.cleanupKeys(managedKeysRef.current);
      manager.removeLink('canonical');
      manager.removeStructuredData('structured-data');
      manager.restoreTitle();
    };
  }, [
    title,
    description,
    keywords,
    image,
    url,
    type,
    author,
    publishedTime,
    modifiedTime,
    structuredData,
  ]);

  return null;
}

/**
 * Generate structured data for a marketplace item (agent/base)
 */
// eslint-disable-next-line react-refresh/only-export-components
export function generateProductStructuredData(item: {
  name: string;
  description: string;
  slug: string;
  price?: number;
  pricing_type?: string;
  rating?: number;
  review_count?: number;
  creator_name?: string;
  avatar_url?: string;
  category?: string;
}) {
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'https://tesslate.com';

  return {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: item.name,
    description: item.description,
    url: `${baseUrl}/marketplace/${item.slug}`,
    applicationCategory: item.category || 'DeveloperApplication',
    operatingSystem: 'Web',
    offers: {
      '@type': 'Offer',
      price: item.price || 0,
      priceCurrency: 'USD',
      availability: 'https://schema.org/InStock',
    },
    ...(item.rating &&
      item.review_count && {
        aggregateRating: {
          '@type': 'AggregateRating',
          ratingValue: item.rating,
          reviewCount: item.review_count,
          bestRating: 5,
          worstRating: 1,
        },
      }),
    ...(item.creator_name && {
      author: {
        '@type': 'Person',
        name: item.creator_name,
      },
    }),
    ...(item.avatar_url && {
      image: item.avatar_url,
    }),
  };
}

/**
 * Generate structured data for marketplace category/browse pages
 */
// eslint-disable-next-line react-refresh/only-export-components
export function generateBreadcrumbStructuredData(items: { name: string; url: string }[]) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.name,
      item: item.url,
    })),
  };
}

/**
 * Generate structured data for the marketplace homepage
 */
// eslint-disable-next-line react-refresh/only-export-components
export function generateMarketplaceStructuredData() {
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'https://tesslate.com';

  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: 'Tesslate Marketplace',
    description:
      'Discover AI-powered coding agents, project templates, and developer tools. Build faster with pre-built solutions.',
    url: `${baseUrl}/marketplace`,
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${baseUrl}/marketplace?search={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    },
  };
}

export default SEO;
