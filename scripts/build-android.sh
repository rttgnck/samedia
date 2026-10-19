#!/bin/bash
# Builds Samedia for Android and installs it on a connected (USB or Wi-Fi debugging) phone or
# Google TV (Chromecast with Google TV etc.; Developer options > USB debugging).
#
#   scripts/build-android.sh [device serial]
#
# Needs Android Studio (its bundled Java and SDK) or JAVA_HOME and ANDROID_HOME set. The APK is
# signed with this computer's Android debug key, which is fine for installing on your own phones
# (android/app/build/outputs/apk/release/app-release.apk can also be copied over and opened).
set -e
cd "$(dirname "$0")/../android"
STUDIO="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
[ -n "$JAVA_HOME" ] || { [ -d "$STUDIO" ] && export JAVA_HOME="$STUDIO"; }
SDK=${ANDROID_HOME:-$HOME/Library/Android/sdk}
[ -f local.properties ] || echo "sdk.dir=$SDK" > local.properties
./gradlew --console=plain -q assembleRelease
APK=app/build/outputs/apk/release/app-release.apk
echo "Built $APK"

ADB="$SDK/platform-tools/adb"
command -v adb >/dev/null && ADB=adb
SERIAL=${1:-$("$ADB" devices | awk 'NR>1 && $2=="device" {print $1; exit}')}
[ -n "$SERIAL" ] || { echo "No phone connected: plug one in with USB debugging on (or pair Wireless debugging), or copy the APK over."; exit 0; }
"$ADB" -s "$SERIAL" install -r "$APK"
# Google TV opens the TV interface, phones the phone one
if "$ADB" -s "$SERIAL" shell pm has-feature android.software.leanback | grep -q true; then
  "$ADB" -s "$SERIAL" shell am start -n io.samedia.player/.tv.TvActivity >/dev/null
else
  "$ADB" -s "$SERIAL" shell am start -n io.samedia.player/.MainActivity >/dev/null
fi
echo "Installed on $SERIAL"
