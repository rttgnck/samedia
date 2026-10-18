#!/bin/bash
# Copies the server's profile pictures into the iOS asset catalog (iOS can't load SVG at runtime,
# but the asset compiler keeps them as vectors).
set -e
cd "$(dirname "$0")/.."
SRC=server/samedia/web/avatars; DST=ios/Samedia/Assets.xcassets/Avatars
for f in "$SRC"/*.svg; do
  name=$(basename "$f" .svg); set_dir="$DST/avatar-$name.imageset"
  mkdir -p "$set_dir" && cp "$f" "$set_dir/$name.svg"
  cat > "$set_dir/Contents.json" <<JSON
{
  "images" : [ { "filename" : "$name.svg", "idiom" : "universal" } ],
  "info" : { "author" : "xcode", "version" : 1 },
  "properties" : { "preserves-vector-representation" : true }
}
JSON
done
echo "synced $(ls "$SRC"/*.svg | wc -l | tr -d ' ') avatars"
