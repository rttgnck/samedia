#!/bin/bash
# Builds Samedia for iPhone/iPad and installs it on a connected (or Wi-Fi paired) device.
#
#   SAMEDIA_TEAM=<team id> scripts/build-ios.sh [device name or id]
#
# SAMEDIA_TEAM: your Apple development team (Xcode > Settings > Accounts; a free personal team
# works, but its apps stop opening after 7 days: run this again). Set SAMEDIA_BUNDLE_ID too if
# the default id is taken for your team.
set -e
cd "$(dirname "$0")/.."
[ -n "$SAMEDIA_TEAM" ] || { echo "Set SAMEDIA_TEAM to your Apple development team id."; exit 1; }
BUNDLE=${SAMEDIA_BUNDLE_ID:-io.samedia.player}
scripts/sync-ios-avatars.sh >/dev/null
cd ios
xcodegen generate --quiet

DEVICE=$1
if [ -z "$DEVICE" ]; then
  J=$(mktemp)
  xcrun devicectl list devices --json-output "$J" >/dev/null
  DEVICE=$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))["result"]["devices"]
ok=[x for x in d if x.get("connectionProperties",{}).get("pairingState")=="paired" and x.get("hardwareProperties",{}).get("platform")=="iOS"]
print(ok[0]["identifier"] if ok else "")' "$J")
  rm -f "$J"
  [ -n "$DEVICE" ] || { echo "No paired iPhone or iPad found."; exit 1; }
fi

xcodebuild -project Samedia.xcodeproj -scheme Samedia -configuration Release -destination "generic/platform=iOS" \
  -derivedDataPath build -allowProvisioningUpdates -quiet \
  DEVELOPMENT_TEAM="$SAMEDIA_TEAM" PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE" build
xcrun devicectl device install app --device "$DEVICE" build/Build/Products/Release-iphoneos/Samedia.app
xcrun devicectl device process launch --device "$DEVICE" "$BUNDLE" || \
  echo "Installed. If it won't open: on the device, Settings > General > VPN & Device Management > trust the developer."
