#!/bin/bash
# Checks the bundle-swap script produced by electron/macUpdate.cjs.
#
# Runs against fake .app bundles in a temp directory, with `open` stubbed so
# nothing can launch. Nothing in /Applications is touched.
#
# The important case is #4: when the ROLLBACK itself fails, the backup must
# survive. An earlier version deleted the staging directory — which contains
# the backup — without checking, so a failed rollback could leave the user with
# no application at all.

DESKTOP="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d -t redaction-swapcheck)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/bin" "$WORK/Apps"
printf '#!/bin/bash\necho "OPEN:$1" >> "%s/calls.log"\n' "$WORK" > "$WORK/bin/open"
chmod +x "$WORK/bin/open"

# Write the script exactly as the app would, then redirect `open` to the stub.
node -e 'const {buildSwapScript}=require(process.argv[1]+"/electron/macUpdate.cjs");require("fs").writeFileSync(process.argv[2],buildSwapScript(),{mode:0o755});' "$DESKTOP" "$WORK/swap.orig.sh" || exit 1
sed "s#/usr/bin/open#$WORK/bin/open#g" "$WORK/swap.orig.sh" > "$WORK/swap.sh"
chmod +x "$WORK/swap.sh"

# A failing-mv variant: the first move (target -> backup) works, everything
# after fails. That drives both the swap AND the rollback into failure.
cat > "$WORK/bin/mv" <<EOF
#!/bin/bash
n=\$(cat "$WORK/mvcount" 2>/dev/null || echo 0); n=\$((n+1)); echo \$n > "$WORK/mvcount"
if [ "\$n" = "1" ]; then exec /bin/mv "\$@"; else exit 1; fi
EOF
chmod +x "$WORK/bin/mv"
sed "s#/bin/mv#$WORK/bin/mv#g" "$WORK/swap.sh" > "$WORK/swap.badmv.sh"
chmod +x "$WORK/swap.badmv.sh"

make_bundle() { mkdir -p "$1/Contents/MacOS"; echo "$2" > "$1/Contents/version.txt"; }
version_of() { cat "$1/Contents/version.txt" 2>/dev/null || echo "MISSING"; }

setup_case() {
  rm -rf "$WORK/Apps" "$WORK/calls.log" "$WORK/swap.log" "$WORK/failure.txt" "$WORK/mvcount"
  mkdir -p "$WORK/Apps"
  TARGET="$WORK/Apps/Redaction Tool.app"        # name deliberately contains a space
  STAGING="$WORK/Apps/.redaction-tool-update"
  mkdir -p "$STAGING"
  make_bundle "$TARGET" "OLD"
}

run_swap() { # $1=pid  $2=script (optional)
  "${2:-$WORK/swap.sh}" "$1" "$TARGET" "$STAGING/Redaction Tool.app" \
    "$STAGING/previous.app" "$STAGING" "$WORK/swap.log" "$WORK/failure.txt"
}

pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
          else echo "  FAIL  $1 (got '$2', wanted '$3')"; fail=$((fail+1)); fi; }

echo "== 1. Happy path: app replaced, relaunched, staging cleaned =="
setup_case
make_bundle "$STAGING/Redaction Tool.app" "NEW"
sleep 1 & pid=$!
run_swap "$pid"; code=$?
check "exit code"          "$code"                    "0"
check "installed version"  "$(version_of "$TARGET")"  "NEW"
check "staging cleaned"    "$([ -d "$STAGING" ] && echo no || echo yes)" "yes"
check "relaunched"         "$(grep -c '^OPEN:' "$WORK/calls.log")"       "1"
check "no failure marker"  "$([ -s "$WORK/failure.txt" ] && echo yes || echo no)" "no"
check "logged success"     "$(grep -c 'swap succeeded' "$WORK/swap.log")" "1"

echo "== 2. Waits for the old process to exit =="
setup_case
make_bundle "$STAGING/Redaction Tool.app" "NEW"
sleep 3 & pid=$!
start=$(date +%s)
run_swap "$pid"; code=$?
elapsed=$(( $(date +%s) - start ))
check "exit code"          "$code"                   "0"
check "installed version"  "$(version_of "$TARGET")" "NEW"
check "waited >=2s"        "$([ "$elapsed" -ge 2 ] && echo yes || echo no)" "yes"

echo "== 3. Staged app missing: rollback restores the original =="
setup_case
sleep 1 & pid=$!
run_swap "$pid" >/dev/null 2>&1; code=$?
check "exit code"              "$code"                    "1"
check "original restored"      "$(version_of "$TARGET")"  "OLD"
check "staging cleaned"        "$([ -d "$STAGING" ] && echo no || echo yes)" "yes"
check "still relaunched"       "$(grep -c '^OPEN:' "$WORK/calls.log")"       "1"
check "failure marker written" "$([ -s "$WORK/failure.txt" ] && echo yes || echo no)" "yes"

echo "== 4. ROLLBACK ALSO FAILS: the backup must survive =="
setup_case
make_bundle "$STAGING/Redaction Tool.app" "NEW"
sleep 1 & pid=$!
run_swap "$pid" "$WORK/swap.badmv.sh" >/dev/null 2>&1; code=$?
check "exit code"               "$code" "1"
check "backup PRESERVED"        "$(version_of "$STAGING/previous.app")" "OLD"
check "staging NOT deleted"     "$([ -d "$STAGING" ] && echo yes || echo no)" "yes"
check "logged rollback failure" "$(grep -c 'ROLLBACK FAILED' "$WORK/swap.log")" "1"
check "failure marker written"  "$([ -s "$WORK/failure.txt" ] && echo yes || echo no)" "yes"

echo
echo "swap-script: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
