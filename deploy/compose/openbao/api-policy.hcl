# The API may create, replace and delete secrets but never read them back.
# There is deliberately no "read" capability on kv/data/* or kv/metadata/*.
path "kv/data/*" {
  capabilities = ["create", "update"]
}

path "kv/metadata/*" {
  capabilities = ["create", "update", "delete", "list"]
}

path "kv/delete/*" {
  capabilities = ["update"]
}

path "kv/destroy/*" {
  capabilities = ["update"]
}

path "transit/encrypt/veyntora" {
  capabilities = ["update"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
