#!/bin/sh
# Local development only: initialise and unseal OpenBao, enable KV v2 + Transit, write the
# API (write-only) and runtime (read-only) policies and issue one token for each.
#
# The root token and unseal key stay in the `openbao-root` volume, which only this job
# mounts. The API and runtime tokens go to separate volumes so no service can read the
# other's token or the root token.
set -eu

export BAO_ADDR="${BAO_ADDR:-http://openbao:8200}"
ROOT_DIR=/state/root
API_DIR=/state/api
RUNTIME_DIR=/state/runtime

status() {
  # Exit code 0 = unsealed, 2 = sealed, anything else = not reachable yet.
  bao status -format=json >/tmp/status.json 2>/dev/null
}

i=0
until status || [ $? -eq 2 ]; do
  i=$((i + 1))
  [ "$i" -gt 60 ] && echo "openbao not reachable" >&2 && exit 1
  sleep 1
done

if ! tr -d ' \n' </tmp/status.json | grep -q '"initialized":true'; then
  echo "initialising openbao"
  bao operator init -key-shares=1 -key-threshold=1 -format=json >"$ROOT_DIR/init.json"
  chmod 600 "$ROOT_DIR/init.json"
fi

INIT=$(tr -d ' \n' <"$ROOT_DIR/init.json")
UNSEAL_KEY=$(echo "$INIT" | sed -n 's/.*"unseal_keys_b64":\["\([^"]*\)".*/\1/p')
ROOT_TOKEN=$(echo "$INIT" | sed -n 's/.*"root_token":"\([^"]*\)".*/\1/p')

if tr -d ' \n' </tmp/status.json | grep -q '"sealed":true' || ! status; then
  echo "unsealing openbao"
  bao operator unseal "$UNSEAL_KEY" >/dev/null
fi

export BAO_TOKEN="$ROOT_TOKEN"

bao secrets list -format=json | tr -d ' \n' | grep -q '"kv/"' ||
  bao secrets enable -path=kv -version=2 kv
bao secrets list -format=json | tr -d ' \n' | grep -q '"transit/"' ||
  bao secrets enable transit
bao read transit/keys/veyntora >/dev/null 2>&1 ||
  bao write -f transit/keys/veyntora >/dev/null

bao policy write veyntora-api /policies/api.hcl >/dev/null
bao policy write veyntora-runtime /policies/runtime.hcl >/dev/null

issue() {
  # Re-issue only if the stored token no longer works.
  policy=$1
  file=$2
  if [ -s "$file" ] && BAO_TOKEN=$(cat "$file") bao token lookup-self >/dev/null 2>&1; then
    return 0
  fi
  bao token create -orphan -policy="$policy" -period=768h -display-name="$policy" -field=token >"$file"
  chmod 644 "$file"
  echo "issued token for $policy"
}

issue veyntora-api "$API_DIR/api.token"
issue veyntora-runtime "$RUNTIME_DIR/runtime.token"
echo "openbao ready"
