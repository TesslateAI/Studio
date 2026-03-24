/**
 * Tests for DeploymentTargetNode deploy type routing.
 *
 * Covers:
 * - getDeployType() correctly classifies all providers
 * - Source providers return 'source'
 * - Container-push providers return 'container'
 * - Export providers return 'export'
 * - Unknown providers default to 'source'
 */

import { describe, it, expect } from 'vitest';
import { getDeployType } from './DeploymentTargetNode';

describe('getDeployType', () => {
  describe('source providers', () => {
    const sourceProviders = [
      'vercel',
      'netlify',
      'cloudflare',
      'railway',
      'render',
      'heroku',
      'koyeb',
      'zeabur',
      'northflank',
      'github-pages',
      'surge',
      'deno-deploy',
      'firebase',
      'digitalocean',
    ];

    it.each(sourceProviders)('classifies "%s" as source', (provider) => {
      expect(getDeployType(provider)).toBe('source');
    });
  });

  describe('container-push providers', () => {
    const containerProviders = [
      'aws-apprunner',
      'gcp-cloudrun',
      'azure-container-apps',
      'do-container',
      'fly',
    ];

    it.each(containerProviders)('classifies "%s" as container', (provider) => {
      expect(getDeployType(provider)).toBe('container');
    });
  });

  describe('export providers', () => {
    const exportProviders = ['dockerhub', 'ghcr', 'download'];

    it.each(exportProviders)('classifies "%s" as export', (provider) => {
      expect(getDeployType(provider)).toBe('export');
    });
  });

  describe('edge cases', () => {
    it('defaults unknown providers to source', () => {
      expect(getDeployType('some-new-provider')).toBe('source');
    });

    it('is case-sensitive (matches backend behavior)', () => {
      expect(getDeployType('AWS-APPRUNNER')).toBe('source');
      expect(getDeployType('aws-apprunner')).toBe('container');
    });
  });
});
