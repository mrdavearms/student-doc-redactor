import { describe, it, expect } from 'vitest';

// Mirrors the routing logic in ConversionStatus.handleContinue.
// If that logic changes, update these tests too.
function routeAfterDetection(documents: { matches: unknown[] }[]): 'no_pii_found' | 'document_review' {
  const totalMatches = documents.reduce((sum, d) => sum + d.matches.length, 0);
  return totalMatches === 0 ? 'no_pii_found' : 'document_review';
}

describe('ConversionStatus: post-detection routing', () => {
  it('routes to no_pii_found when all documents have zero matches', () => {
    expect(routeAfterDetection([{ matches: [] }, { matches: [] }])).toBe('no_pii_found');
  });

  it('routes to no_pii_found when there are no documents at all', () => {
    expect(routeAfterDetection([])).toBe('no_pii_found');
  });

  it('routes to document_review when one document has matches', () => {
    expect(routeAfterDetection([{ matches: [{}] }, { matches: [] }])).toBe('document_review');
  });

  it('routes to document_review when all documents have matches', () => {
    expect(routeAfterDetection([{ matches: [{}, {}] }, { matches: [{}] }])).toBe('document_review');
  });

  it('routes to document_review for a single document with one match', () => {
    expect(routeAfterDetection([{ matches: [{}] }])).toBe('document_review');
  });
});
