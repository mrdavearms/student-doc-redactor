/**
 * Proving that the backend answering on our port is the one we spawned,
 * without handing the session token to whoever answers.
 *
 * A healthy port does not mean the backend is ours: an orphan left by a
 * force-quit, or a second copy of the app, can hold 8765 first (CLAUDE.md
 * rule 55). The old check sent X-Api-Token to the listener and believed its
 * `instance_match: true` reply, so any process on the port received the token
 * and could simply say yes.
 *
 * Now each probe sends a fresh random nonce. Only a process that already
 * knows the token can answer with HMAC-SHA256(token, nonce), and a fresh nonce
 * per probe means an earlier answer cannot be replayed.
 *
 * Kept out of main.cjs so it can be unit-tested; see backendIdentity.test.ts.
 */

const crypto = require('node:crypto');

const PROOF_PATTERN = /^[0-9a-f]{64}$/;

/** @returns {string} 32 random bytes as lowercase hex. */
function newNonce() {
  return crypto.randomBytes(32).toString('hex');
}

/**
 * Headers for an identity probe. Deliberately never includes X-Api-Token:
 * the listener has not proved who it is yet.
 * @param {string} nonce
 */
function healthHeaders(nonce) {
  return { 'X-Health-Nonce': nonce };
}

/**
 * @param {unknown} body   Parsed /api/health response.
 * @param {string} token   This session's API token.
 * @param {string} nonce   The nonce sent with this probe.
 * @returns {boolean}      True only for a correct proof for this nonce.
 */
function isOwnBackend(body, token, nonce) {
  if (!token || !body || typeof body !== 'object') return false;
  const proof = body.proof;
  if (typeof proof !== 'string' || !PROOF_PATTERN.test(proof)) return false;
  const expected = crypto.createHmac('sha256', token).update(nonce).digest('hex');
  return crypto.timingSafeEqual(Buffer.from(proof, 'utf8'), Buffer.from(expected, 'utf8'));
}

module.exports = { newNonce, healthHeaders, isOwnBackend };
