import { describe, it, expect } from 'vitest';
import { createHmac } from 'node:crypto';
// @ts-expect-error — plain CJS module, loaded directly by the Electron main process.
import { newNonce, healthHeaders, isOwnBackend } from '../electron/backendIdentity.cjs';

const TOKEN = 'this-run-token';

function proofFor(token: string, nonce: string): string {
  return createHmac('sha256', token).update(nonce).digest('hex');
}

describe('newNonce', () => {
  it('is 32 random bytes as lowercase hex, different every time', () => {
    const a = newNonce();
    const b = newNonce();
    expect(a).toMatch(/^[0-9a-f]{64}$/);
    expect(b).toMatch(/^[0-9a-f]{64}$/);
    expect(a).not.toBe(b);
  });
});

describe('healthHeaders', () => {
  it('healthHeaders never carries the token', () => {
    const nonce = newNonce();
    const headers = healthHeaders(nonce);
    expect(headers).toEqual({ 'X-Health-Nonce': nonce });
    expect(Object.keys(headers).map((k) => k.toLowerCase())).not.toContain('x-api-token');
    expect(JSON.stringify(headers)).not.toContain(TOKEN);
  });
});

describe('isOwnBackend', () => {
  it('rejects a peer that claims instance_match true', () => {
    // The old protocol's answer. A listener that received the token could
    // simply say yes; it must earn nothing now.
    const nonce = newNonce();
    expect(isOwnBackend({ status: 'ok', instance_match: true }, TOKEN, nonce)).toBe(false);
  });

  it('rejects a wrong proof', () => {
    const nonce = newNonce();
    // Signed with another run's token: the orphan-from-a-force-quit case.
    expect(isOwnBackend({ proof: proofFor('previous-run-token', nonce) }, TOKEN, nonce)).toBe(false);
    // Right token, but replayed from an earlier probe's nonce.
    expect(isOwnBackend({ proof: proofFor(TOKEN, newNonce()) }, TOKEN, nonce)).toBe(false);
  });

  it('accepts the correct HMAC', () => {
    const nonce = newNonce();
    expect(isOwnBackend({ status: 'ok', proof: proofFor(TOKEN, nonce) }, TOKEN, nonce)).toBe(true);
  });

  it('rejects malformed or missing proofs without throwing', () => {
    const nonce = newNonce();
    const good = proofFor(TOKEN, nonce);
    for (const body of [
      {},
      { proof: null },
      { proof: 42 },
      { proof: '' },
      { proof: good.slice(0, 63) },
      { proof: good + '0' },
      { proof: good.toUpperCase() },
      { proof: 'z'.repeat(64) },
      null,
      undefined,
      'ok',
    ]) {
      expect(isOwnBackend(body, TOKEN, nonce)).toBe(false);
    }
  });

  it('never accepts anything when there is no token to prove', () => {
    const nonce = newNonce();
    expect(isOwnBackend({ proof: proofFor('', nonce) }, '', nonce)).toBe(false);
  });
});
