#!/bin/sh
# Container entrypoint: fill the /app/data volume from the image's shipped data,
# then exec the service command.
#
#  * calendars/        — reference data: ALWAYS refreshed from the image, so a
#                        new image brings new holiday tables.
#  * case_registry.json, tenant_dicts/
#                      — operator-owned (edited via the admin API / file drop):
#                        copied only when ABSENT, never overwritten.
set -eu
SEED=/app/data-seed
DATA=/app/data
mkdir -p "$DATA"

if [ -d "$SEED/calendars" ]; then
  rm -rf "$DATA/calendars"
  cp -R "$SEED/calendars" "$DATA/calendars"
fi
if [ -f "$SEED/case_registry.json" ] && [ ! -e "$DATA/case_registry.json" ]; then
  cp "$SEED/case_registry.json" "$DATA/case_registry.json"
fi
if [ -d "$SEED/tenant_dicts" ] && [ ! -e "$DATA/tenant_dicts" ]; then
  cp -R "$SEED/tenant_dicts" "$DATA/tenant_dicts"
fi

exec "$@"
