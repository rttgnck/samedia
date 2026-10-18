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
TV_IP="${1:-}"
PROFILE="${TIZEN_PROFILE:-}"

command -v tizen >/dev/null || { echo "tizen CLI not found. Add ~/tizen-studio/tools/ide/bin to PATH." >&2; exit 1; }

rm -rf "$BUILD" && mkdir -p "$BUILD"
cp -R "$ROOT/tv/config.xml" "$ROOT/tv/index.html" "$ROOT/tv/icon.png" "$ROOT/tv/css" "$ROOT/tv/js" "$BUILD/"

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
  command -v sdb >/dev/null || { echo "sdb not found. Add ~/tizen-studio/tools to PATH." >&2; exit 1; }
  echo "→ Connecting to $TV_IP"
  sdb connect "$TV_IP"
  TARGET="$(sdb devices | awk 'NR>1 && $1 ~ /'"$TV_IP"'/ {print $3}' | head -1)"
  echo "→ Installing on ${TARGET:-$TV_IP}"
  tizen install -n "$ROOT/dist/Samedia.wgt" ${TARGET:+-t "$TARGET"}
  tizen run -p SamediaTV0.Samedia ${TARGET:+-t "$TARGET"} || true
fi
