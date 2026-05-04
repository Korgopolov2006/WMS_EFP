#!/usr/bin/env sh
set -eu

DEMO_DUMP="/backups/wms_demo_dump.sql"

if [ -f "$DEMO_DUMP" ]; then
  echo "Found demo dump: $DEMO_DUMP"
  echo "Restoring demo data into database: $POSTGRES_DB"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" < "$DEMO_DUMP"
  echo "Demo dump restored successfully."
else
  echo "Demo dump not found at $DEMO_DUMP. Starting with an empty database."
fi
