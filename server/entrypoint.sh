#!/bin/sh
# Start as root only long enough to make /config writable, then drop to PUID:PGID.
# (Docker creates missing bind-mount folders as root, e.g. /opt/nasos/config/samedia.)
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "${SAMEDIA_DATA_DIR:-/config}"
  chown -R "$PUID:$PGID" "${SAMEDIA_DATA_DIR:-/config}"
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi
exec "$@"
