#!/bin/sh
# Dump the local database to ./backups (git ignored). Custom format, restore with pg_restore.
# For Supabase, run pg_dump yourself with the session pooler URL before risky changes.
set -e
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S)
docker compose exec -T db pg_dump -U backroom --format=custom backroom > "backups/backroom-$stamp.dump"
echo "Wrote backups/backroom-$stamp.dump"
