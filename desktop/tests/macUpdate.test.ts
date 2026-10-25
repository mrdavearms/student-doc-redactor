import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
// @ts-expect-error — plain CJS module, no types
import macUpdate from '../electron/macUpdate.cjs';

const {
  REPO_OWNER,
  REPO_NAME,
  BUNDLE_ID,
  safeAssetName,
  downloadUrlFor,
  pickMacAsset,
  selfUpdateBlockedReason,
  stagedUpdateIsUsable,
  isNewerVersion,
  stagingPaths,
  decideRestart,
  stagingIsTrusted,
  STAGED_APP_NAME,
  STAGING_DIR_NAME,
  buildSwapScript,
} = macUpdate;

// The exact asset name a real release publishes, taken from the live
// latest-mac.yml for v1.6.2. electron-builder replaces spaces with dashes for
// the published name, so the manifest never contains a space even though the
// local artifact does.
const REAL_ASSET = 'Redaction-Tool-1.6.2-arm64.dmg';

describe('config constants stay in step with package.json', () => {
  const pkg = JSON.parse(
    readFileSync(resolve(__dirname, '../package.json'), 'utf8')
  );

  it('bundle id matches build.appId', () => {
    expect(BUNDLE_ID).toBe(pkg.build.appId);
  });

  it('owner and repo match build.publish', () => {
    // Detection uses build.publish; the download URL uses these constants. If
    // they drift, updates fail silently — detection works, downloads 404.
    expect(REPO_OWNER).toBe(pkg.build.publish.owner);
    expect(REPO_NAME).toBe(pkg.build.publish.repo);
  });
});

describe('safeAssetName', () => {
  it('passes a real published asset name through unchanged', () => {
    expect(safeAssetName(REAL_ASSET)).toBe(REAL_ASSET);
  });

  it('substitutes dashes for spaces, matching electron-builder and electron-updater', () => {
    // Percent-encoding here would 404: the published name uses dashes.
    expect(safeAssetName('Redaction Tool-1.7.0-arm64.dmg')).toBe(
      'Redaction-Tool-1.7.0-arm64.dmg'
    );
  });

  it('rejects anything that is not a plain filename', () => {
    expect(safeAssetName('../../etc/passwd')).toBeNull();
    expect(safeAssetName('nested/path.dmg')).toBeNull();
    expect(safeAssetName('back\\slash.dmg')).toBeNull();
    expect(safeAssetName('')).toBeNull();
    expect(safeAssetName(undefined)).toBeNull();
  });
});

describe('downloadUrlFor', () => {
  it('builds the real release URL for the real asset name', () => {
    expect(downloadUrlFor({ version: '1.6.2', fileName: REAL_ASSET })).toBe(
      `https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/download/v1.6.2/${REAL_ASSET}`
    );
  });

  it('does not double up the v when the version already has one', () => {
    expect(downloadUrlFor({ version: 'v1.6.3', fileName: 'a.dmg' })).toContain('/download/v1.6.3/');
  });

  it('returns null rather than a traversal URL', () => {
    expect(downloadUrlFor({ version: '1.6.3', fileName: '../../../evil.dmg' })).toBeNull();
    expect(downloadUrlFor({ version: '', fileName: 'a.dmg' })).toBeNull();
  });
});

describe('pickMacAsset', () => {
  it('picks the single dmg a real release publishes', () => {
    // Shape copied from the live latest-mac.yml: one entry, no blockmap.
    const files = [{ url: REAL_ASSET, sha512: 'abc', size: 595385203 }];
    expect(pickMacAsset(files, 'arm64')?.url).toBe(REAL_ASSET);
  });

  it('prefers the dmg over a zip, because the zip path has never shipped', () => {
    const files = [
      { url: 'app-1.7.0-arm64-mac.zip', sha512: 'b' },
      { url: 'app-1.7.0-arm64.dmg', sha512: 'a' },
    ];
    expect(pickMacAsset(files, 'arm64')?.url).toBe('app-1.7.0-arm64.dmg');
  });

  it('falls back to a zip when that is genuinely all there is', () => {
    const files = [{ url: 'app-1.7.0-arm64-mac.zip', sha512: 'b' }];
    expect(pickMacAsset(files, 'arm64')?.url).toBe('app-1.7.0-arm64-mac.zip');
  });

  it('picks the matching architecture when a release ships both', () => {
    const files = [
      { url: 'Redaction-Tool-1.7.0-x64.dmg', sha512: 'a' },
      { url: 'Redaction-Tool-1.7.0-arm64.dmg', sha512: 'b' },
    ];
    expect(pickMacAsset(files, 'arm64')?.url).toBe('Redaction-Tool-1.7.0-arm64.dmg');
    expect(pickMacAsset(files, 'x64')?.url).toBe('Redaction-Tool-1.7.0-x64.dmg');
  });

  it('refuses to guess when several candidates are indistinguishable', () => {
    // Better a manual download than an Intel build on an Apple Silicon Mac.
    const files = [
      { url: 'Redaction-Tool-1.7.0.dmg', sha512: 'a' },
      { url: 'Redaction-Tool-1.7.0-alt.dmg', sha512: 'b' },
    ];
    expect(pickMacAsset(files, 'arm64')).toBeNull();
  });

  it('ignores blockmaps and other non-installable files', () => {
    const files = [
      { url: `${REAL_ASSET}.blockmap`, sha512: 'a' },
      { url: REAL_ASSET, sha512: 'b' },
    ];
    expect(pickMacAsset(files, 'arm64')?.url).toBe(REAL_ASSET);
  });

  it('returns null for missing or malformed input', () => {
    expect(pickMacAsset(undefined, 'arm64')).toBeNull();
    expect(pickMacAsset([], 'arm64')).toBeNull();
    expect(pickMacAsset([{ sha512: 'a' }], 'arm64')).toBeNull();
  });
});

describe('selfUpdateBlockedReason', () => {
  const ok = {
    platform: 'darwin',
    isPackaged: true,
    appPath: '/Applications/Redaction Tool.app',
    appWritable: true,
    parentWritable: true,
  };

  it('allows a normal writable install in /Applications', () => {
    expect(selfUpdateBlockedReason(ok)).toBeNull();
  });

  it('blocks Windows and Linux', () => {
    expect(selfUpdateBlockedReason({ ...ok, platform: 'win32' })).toBe('not macOS');
  });

  it('blocks dev builds', () => {
    expect(selfUpdateBlockedReason({ ...ok, isPackaged: false })).toBe('development build');
  });

  it('blocks an app still running from the mounted disk image', () => {
    expect(
      selfUpdateBlockedReason({ ...ok, appPath: '/Volumes/Redaction Tool 1.6.2/Redaction Tool.app' })
    ).toBe('running from the disk image');
  });

  it('blocks an install the user cannot write to', () => {
    expect(selfUpdateBlockedReason({ ...ok, appWritable: false })).toBe(
      'no permission to replace the app'
    );
    expect(selfUpdateBlockedReason({ ...ok, parentWritable: false })).toBe(
      'no permission to replace the app'
    );
  });

  it('blocks anything that is not an .app bundle', () => {
    expect(selfUpdateBlockedReason({ ...ok, appPath: '/usr/local/bin/redaction' })).toBe(
      'not an application bundle'
    );
  });
});

describe('stagedUpdateIsUsable', () => {
  const marker = {
    version: '1.6.3',
    bundleId: BUNDLE_ID,
    stagedApp: '/Applications/.redaction-tool-update/Redaction Tool.app',
    scriptPath: '/Applications/.redaction-tool-update/swap.sh',
  };

  it('accepts a complete marker for the offered version', () => {
    expect(stagedUpdateIsUsable(marker, { version: '1.6.3', bundleId: BUNDLE_ID })).toBe(true);
  });

  it('accepts when no particular version is being asked about', () => {
    expect(stagedUpdateIsUsable(marker, {})).toBe(true);
  });

  it('rejects a marker for a different version', () => {
    expect(stagedUpdateIsUsable(marker, { version: '1.6.4' })).toBe(false);
  });

  it('rejects a marker for a different application', () => {
    expect(stagedUpdateIsUsable(marker, { bundleId: 'com.someone.else' })).toBe(false);
  });

  it('rejects incomplete or absent markers', () => {
    expect(stagedUpdateIsUsable(null, {})).toBe(false);
    expect(stagedUpdateIsUsable({ version: '1.6.3' }, {})).toBe(false);
    expect(stagedUpdateIsUsable({ ...marker, scriptPath: undefined }, {})).toBe(false);
  });
});

describe('isNewerVersion', () => {
  it('older staged version is not adopted', () => {
    expect(isNewerVersion('1.9.4', '1.9.5')).toBe(false);
    expect(isNewerVersion('1.9.9', '1.10.0')).toBe(false);
  });

  it('equal version is not adopted', () => {
    expect(isNewerVersion('1.9.5', '1.9.5')).toBe(false);
  });

  it('a newer version is adopted, comparing numbers not strings', () => {
    expect(isNewerVersion('1.10.0', '1.9.9')).toBe(true);
    expect(isNewerVersion('2.0.0', '1.99.99')).toBe(true);
  });

  it('a pre-release sorts below its own release', () => {
    expect(isNewerVersion('1.9.5-beta.1', '1.9.5')).toBe(false);
    expect(isNewerVersion('1.9.5', '1.9.5-beta.1')).toBe(true);
  });

  it('rejects anything that is not a dotted version', () => {
    expect(isNewerVersion('garbage', '1.0.0')).toBe(false);
    expect(isNewerVersion(undefined, '1.0.0')).toBe(false);
    expect(isNewerVersion('1.0.0', 'garbage')).toBe(false);
  });
});

describe('stagingPaths', () => {
  it('stagingPaths derives every path from the app folder', () => {
    const p = stagingPaths('/Applications/Redaction Tool.app');
    const dir = `/Applications/${STAGING_DIR_NAME}`;
    expect(p).toEqual({
      stagingDir: dir,
      stagedApp: `${dir}/${STAGED_APP_NAME}`,
      backupPath: `${dir}/previous.app`,
      scriptPath: `${dir}/swap.sh`,
    });
  });
});

describe('staged name is fixed', () => {
  it('does not depend on the installed app name', () => {
    const p = stagingPaths('/Applications/Redaction Tool 2.app');
    expect(p.stagedApp).toBe(`${p.stagingDir}/${STAGED_APP_NAME}`);
  });

  it('the installer stages under the same constant', () => {
    const src = readFileSync(resolve(__dirname, '../electron/macUpdateInstaller.cjs'), 'utf8');
    expect(src).toContain('path.join(stagingDir, STAGED_APP_NAME)');
    // dmg and zip paths both stage under it.
    expect(src.split('path.join(stagingDir, STAGED_APP_NAME)').length - 1).toBeGreaterThanOrEqual(2);
  });
});

describe('decideRestart', () => {
  const appPath = '/Applications/Redaction Tool 2.app';
  const p = stagingPaths(appPath);
  const base = { appPath, bundleId: BUNDLE_ID };

  it('installs when files exist and the bundle id matches, for any installed name', async () => {
    const r = await decideRestart({
      ...base, exists: (f: string) => f === p.scriptPath || f === p.stagedApp,
      readBundleId: async () => BUNDLE_ID,
    });
    expect(r.action).toBe('install');
    expect(r.paths.stagedApp).toBe(p.stagedApp);
  });

  it('aborts and cleans when the staged files are missing', async () => {
    const r = await decideRestart({ ...base, exists: () => false, readBundleId: async () => BUNDLE_ID });
    expect(r).toMatchObject({ action: 'abort', clean: true });
  });

  it('aborts and cleans on a foreign bundle id', async () => {
    const r = await decideRestart({ ...base, exists: () => true, readBundleId: async () => 'com.someone.else' });
    expect(r).toMatchObject({ action: 'abort', clean: true });
  });

  it('aborts and cleans when the bundle id cannot be read', async () => {
    const r = await decideRestart({
      ...base, exists: () => true, readBundleId: async () => { throw new Error('x'); },
    });
    expect(r).toMatchObject({ action: 'abort', clean: true });
  });
});

describe('stagingIsTrusted', () => {
  const st = (o = {}) => ({
    isSymbolicLink: () => false, isDirectory: () => true, uid: 501, mode: 0o40700, ...o,
  });
  it('accepts own, private, real directories', () => {
    expect(stagingIsTrusted([st(), st()], 501)).toBe(true);
  });
  it('rejects a symlink, another owner, group/other-writable, or missing', () => {
    expect(stagingIsTrusted([st({ isSymbolicLink: () => true })], 501)).toBe(false);
    expect(stagingIsTrusted([st({ uid: 0 })], 501)).toBe(false);
    expect(stagingIsTrusted([st({ mode: 0o40770 })], 501)).toBe(false);
    expect(stagingIsTrusted([st({ mode: 0o40707 })], 501)).toBe(false);
    expect(stagingIsTrusted([st(), null], 501)).toBe(false);
    expect(stagingIsTrusted([], 501)).toBe(false);
  });
  it('decideRestart aborts and cleans on an untrusted staging folder', async () => {
    const r = await decideRestart({
      appPath: '/Applications/Redaction Tool.app', bundleId: BUNDLE_ID,
      exists: () => true, readBundleId: async () => BUNDLE_ID,
      lstat: () => st({ mode: 0o40777 }), uid: 501,
    });
    expect(r).toMatchObject({ action: 'abort', clean: true });
  });
});

describe('buildSwapScript', () => {
  const script = buildSwapScript();

  it('quotes every path so names with spaces survive', () => {
    // "Redaction Tool.app" is the real bundle name — an unquoted $TARGET would
    // delete "/Applications/Redaction" and fail on "Tool.app".
    expect(script).not.toMatch(/\brm -rf \$[A-Z]/);
    expect(script).not.toMatch(/\bmv \$[A-Z]/);
    expect(script).toContain('/bin/mv -- "$TARGET" "$BACKUP"');
    expect(script).toContain('/bin/mv -- "$STAGED" "$TARGET"');
  });

  it('checks the rollback succeeded before deleting anything', () => {
    // The backup lives inside $STAGING. Deleting it after a FAILED rollback
    // leaves the user with no app at all — which is what the earlier version did.
    const rollback = script.indexOf('/bin/mv -- "$BACKUP" "$TARGET"');
    expect(rollback).toBeGreaterThan(-1);
    expect(script).toMatch(/if \/bin\/mv -- "\$BACKUP" "\$TARGET"; then[\s\S]*?rm -rf -- "\$STAGING"/);
    expect(script).toContain('ROLLBACK FAILED');
  });

  it('does not use `set -e`, which would abort before the rollback', () => {
    expect(script).not.toMatch(/^set -e/m);
  });

  it('waits for the old process to exit before touching anything', () => {
    const waitAt = script.indexOf('kill -0 "$PID"');
    const firstMove = script.indexOf('/bin/mv -- "$TARGET"');
    expect(waitAt).toBeGreaterThan(-1);
    expect(waitAt).toBeLessThan(firstMove);
  });

  it('records every failure to a log and a marker file', () => {
    // Without these, a post-quit failure is completely invisible and the app
    // silently re-downloads the update on every launch.
    expect(script).toContain('MARKER');
    expect(script).toMatch(/fail\(\)/);
    const failCalls = script.match(/\bfail "/g) ?? [];
    expect(failCalls.length).toBeGreaterThanOrEqual(3);
  });

  it('relaunches the app on the success and both failure paths', () => {
    expect(script.match(/\/usr\/bin\/open "\$TARGET"/g)?.length).toBeGreaterThanOrEqual(3);
  });

  it('uses absolute paths for the tools it runs', () => {
    for (const bin of ['/bin/mv', '/bin/rm', '/bin/sleep', '/usr/bin/open', '/usr/bin/seq']) {
      expect(script).toContain(bin);
    }
  });

  it('no longer strips the quarantine flag', () => {
    // A programmatic download is never quarantined, so this did nothing except
    // act as a Gatekeeper bypass — and /usr/bin/xattr can trigger the Command
    // Line Tools installer on machines without them.
    expect(script).not.toContain('xattr');
  });

  it('pauses before relaunching so the old backend can free its port', () => {
    expect(script).toMatch(/\/bin\/sleep 2\n\/usr\/bin\/open "\$TARGET"/);
  });
});
