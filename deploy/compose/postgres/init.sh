#!/bin/sh
# Creates one role and database per service from VEY_DATABASES ("name:password,...").
# Each service gets its own credentials and can only reach its own database.
set -eu

echo "$VEY_DATABASES" | tr ',' '\n' | while IFS=: read -r name password; do
  [ -z "$name" ] && continue
  echo "creating database $name"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE "$name" LOGIN PASSWORD '$password';
CREATE DATABASE "$name" OWNER "$name";
REVOKE ALL ON DATABASE "$name" FROM PUBLIC;
SQL
done
