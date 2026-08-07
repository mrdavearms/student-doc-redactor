import { describe, it, expect } from 'vitest';
// @ts-expect-error — plain CJS module, loaded directly by the Electron main process.
import { isAllowedNavigation } from '../electron/navigation.cjs';

const DEV = 'http://localhost:5173';
const MAC_APP = 'file:///Applications/Redaction%20Tool.app/Contents/Resources/dist/index.html';
const WIN_APP = 'file:///C:/Program%20Files/Redaction%20Tool/resources/dist/index.html';

describe('isAllowedNavigation — packaged (file:)', () => {
  it('allows the app reloading its own page', () => {
    expect(isAllowedNavigation(MAC_APP, MAC_APP)).toBe(true);
  });

  it('allows a Windows file URL to reload itself', () => {
    // The case most likely to break silently: getting this wrong would block
    // the app from loading its OWN page on Windows.
    expect(isAllowedNavigation(WIN_APP, WIN_APP)).toBe(true);
  });

  it('allows a hash or query on the same document', () => {
    expect(isAllowedNavigation(`${MAC_APP}#/step/2`, MAC_APP)).toBe(true);
    expect(isAllowedNavigation(`${MAC_APP}?v=2`, MAC_APP)).toBe(true);
  });

  it('treats an encoded and decoded path as the same document', () => {
    const decoded = 'file:///Applications/Redaction Tool.app/Contents/Resources/dist/index.html';
    expect(isAllowedNavigation(decoded, MAC_APP)).toBe(true);
  });

  it('blocks another local file', () => {
    expect(isAllowedNavigation('file:///etc/passwd', MAC_APP)).toBe(false);
  });

  it('blocks a sibling file in the same directory', () => {
    const sibling = MAC_APP.replace('index.html', 'other.html');
    expect(isAllowedNavigation(sibling, MAC_APP)).toBe(false);
  });

  it('blocks any remote URL', () => {
    expect(isAllowedNavigation('https://example.com', MAC_APP)).toBe(false);
    expect(isAllowedNavigation('http://127.0.0.1:8765/api/health', MAC_APP)).toBe(false);
  });
});

describe('isAllowedNavigation — dev server (http:)', () => {
  it('allows the dev server origin', () => {
    expect(isAllowedNavigation(`${DEV}/`, DEV)).toBe(true);
    expect(isAllowedNavigation(`${DEV}/index.html`, DEV)).toBe(true);
  });

  it('blocks a different port on the same host', () => {
    // The backend is on 8765; the renderer must never navigate to it.
    expect(isAllowedNavigation('http://localhost:8765/', DEV)).toBe(false);
  });

  it('blocks a different host', () => {
    expect(isAllowedNavigation('https://example.com', DEV)).toBe(false);
  });

  it('blocks a file URL when running against the dev server', () => {
    expect(isAllowedNavigation('file:///etc/passwd', DEV)).toBe(false);
  });
});

describe('isAllowedNavigation — malformed input', () => {
  it.each(['', 'not a url', 'javascript:alert(1)', '//evil.com'])(
    'blocks %j',
    (target) => {
      expect(isAllowedNavigation(target as string, MAC_APP)).toBe(false);
    },
  );

  it('blocks everything when the app URL itself is unusable', () => {
    expect(isAllowedNavigation(MAC_APP, '')).toBe(false);
  });
});
