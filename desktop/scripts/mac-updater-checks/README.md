# macOS updater checks

Integration checks for the macOS self-updater (`electron/macUpdate.cjs` and
`electron/macUpdateInstaller.cjs`). They are **not** part of `npm test`:

- they only run on macOS (they use `hdiutil`, `ditto`, `PlistBuddy`, `codesign`)
- one of them downloads a small file from the live GitHub release
- `npm test` also runs on the Windows CI runner, where all of that fails

The pure logic in `macUpdate.cjs` **is** unit-tested — see
`desktop/tests/macUpdate.test.ts`. These cover the I/O half, which has no unit
tests because mocking `hdiutil` and a half-gigabyte download would only test
the mocks.

## Running them

```bash
cd desktop && npm run verify:mac-updater
```

Each script is standalone and can be run on its own. They work in a temp
directory and clean up after themselves; nothing in `/Applications` is touched.

| Script | Covers |
|---|---|
| `swap-script.sh` | The bundle swap: happy path, waiting for the old process, rollback when the staged app is missing, and **rollback failure — where the backup must survive** |
| `installer.mjs` | Mounting a disk image, `ditto` preserving framework symlinks, reading bundle id/version, a real download with SHA-512, and **refusing to write through a planted symlink** |
| `persistence.mjs` | Re-adopting an update staged before a relaunch, and rejecting stale, mismatched, corrupt or vanished markers |

## When to run them

- After touching either updater module.
- **After any electron-builder or electron bump** — `installer.mjs` exercises
  the real release manifest, so it catches asset-naming or format changes.
- Before cutting a release that changes updater behaviour.

## What they deliberately do NOT cover

The end-to-end update — a packaged app replacing itself — cannot be automated
here: it needs a signed build installed in `/Applications`, a published release
to update to, and a click. Do that by hand before shipping updater changes.
The method that worked: build with the version set *below* the latest published
release, ad-hoc sign it as CI does, install it, and let it update itself to the
real release. See the Auto-Update section of the root `CLAUDE.md`.
