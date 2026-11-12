#!/bin/bash
# Nightly pg_dump with retention. Runs as the `backup` compose service.
#
# Restore (stops serving while it runs — see docs/deployment.md):
#   gunzip -c backups/<file>.sql.gz | docker compose ... exec -T db psql -U <user> -d <db>
# pipefail: a failed pg_dump must fail the pipeline, not be masked by gzip.
set -euo pipefail

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
mkdir -p /backups

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="/backups/${PGDATABASE}-${stamp}.sql.gz"
  # Write to a temporary name first: an interrupted dump must never look like
  # a complete backup to whoever restores from this directory.
  if pg_dump --no-owner --no-privileges | gzip -9 > "${target}.partial"; then
    mv "${target}.partial" "${target}"
    echo "{\"level\":\"INFO\",\"message\":\"backup written\",\"file\":\"${target}\"}"
  else
    rm -f "${target}.partial"
    echo "{\"level\":\"ERROR\",\"message\":\"backup failed\"}" >&2
  fi
  find /backups -name '*.sql.gz' -mtime "+${KEEP_DAYS}" -delete
  sleep "${INTERVAL}"
done
