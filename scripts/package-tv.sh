#!/usr/bin/env bash
# Build, sign and (optionally) install the Samedia Tizen app.
#
#   scripts/package-tv.sh                  # build dist/Samedia.wgt with the active certificate profile
#   scripts/package-tv.sh 192.168.1.50     # ...and install + launch it on the TV at that IP
#
# Needs Tizen Studio's CLI on PATH (tizen, sdb) and a Samsung certificate profile
# (see tv/README.md). Override the profile with TIZEN_PROFILE=<name>.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/dist/tv"
# Options: --devlog <url>  send the app's diagnostic log to <url> (development builds only)
DEVLOG=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --devlog) DEVLOG="${2:?--devlog needs a URL}"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
TV_IP="${ARGS[0]:-}"
PROFILE="${TIZEN_PROFILE:-}"

if [ -n "$TV_IP" ] && ! [[ "$TV_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo "Expected the TV's IP address, e.g. scripts/package-tv.sh 192.168.1.50 (got: $TV_IP)" >&2
  exit 1
fi

# Use Tizen Studio from its default location when it isn't on PATH
TIZEN_HOME="${TIZEN_STUDIO:-$HOME/tizen-studio}"
for dir in "$TIZEN_HOME/tools/ide/bin" "$TIZEN_HOME/tools"; do
  [ -d "$dir" ] && PATH="$dir:$PATH"
done

command -v tizen >/dev/null || { echo "tizen CLI not found. Install Tizen Studio (see tv/README.md) or set TIZEN_STUDIO=<its folder>." >&2; exit 1; }

rm -rf "$BUILD" && mkdir -p "$BUILD"
cp -R "$ROOT/tv/config.xml" "$ROOT/tv/index.html" "$ROOT/tv/icon.png" "$ROOT/tv/css" "$ROOT/tv/js" "$BUILD/"

# Release builds (scripts/release.mjs): the version in config.xml and the build the app reports
if [ -n "${SAMEDIA_VERSION:-}" ]; then
  sed -i '' -E 's/(<widget[^>]* version=")[0-9.]+"/\1'"$SAMEDIA_VERSION"'"/' "$BUILD/config.xml"
fi
if [ -n "${SAMEDIA_BUILD:-}" ]; then
  printf 'window.SM_BUILD = %s;\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$SAMEDIA_BUILD")" > "$BUILD/js/build-info.js"
  python3 - "$BUILD/index.html" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace('<script src="js/core/util.js"></script>',
              '<script src="js/build-info.js"></script>\n  <script src="js/core/util.js"></script>', 1)
open(p, "w").write(s)
PY
fi

if [ -n "$DEVLOG" ]; then
  # Diagnostic build: define SM_DEV before any app script runs
  printf 'window.SM_DEV = { logUrl: %s };\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$DEVLOG")" > "$BUILD/js/dev-config.js"
  python3 - "$BUILD/index.html" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace('<script src="js/core/util.js"></script>',
              '<script src="js/dev-config.js"></script>\n  <script src="js/core/util.js"></script>', 1)
open(p, "w").write(s)
PY
  echo "→ Diagnostic build: logging to $DEVLOG"
fi

echo "→ Packaging"
if [ -n "$PROFILE" ]; then
  tizen package -t wgt -s "$PROFILE" -- "$BUILD"
else
  tizen package -t wgt -- "$BUILD"
fi
WGT="$(ls "$BUILD"/*.wgt | head -1)"
mv "$WGT" "$ROOT/dist/Samedia.wgt"
echo "✓ $ROOT/dist/Samedia.wgt"

if [ -n "$TV_IP" ]; then
  command -v sdb >/dev/null || { echo "sdb not found in Tizen Studio's tools folder." >&2; exit 1; }
  echo "→ Connecting to $TV_IP"
  sdb connect "$TV_IP" >/dev/null 2>&1 || true
  # "connected to" and "already connected" both end up listed as a device
  if ! sdb devices | grep -q "^$TV_IP:.*device"; then
    echo "Couldn't connect to the TV at $TV_IP. On the TV: Apps → 1 2 3 4 5 → Developer mode On," >&2
    echo "Host PC IP = this computer's IP, then hold the power button to restart the TV." >&2
    exit 1
  fi
  # By its serial (ip:port): the model name in the third column isn't always a valid -t target
  SERIAL="$(sdb devices | awk 'NR>1 && $1 ~ /^'"$TV_IP"':/ {print $1}' | head -1)"
  echo "→ Installing on $SERIAL"
  tizen install -n "$ROOT/dist/Samedia.wgt" -s "$SERIAL"
  tizen run -p SamediaTV0.Samedia -s "$SERIAL" || true
fi
