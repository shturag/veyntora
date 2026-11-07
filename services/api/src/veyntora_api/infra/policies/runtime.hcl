# Graphs and workers resolve secret_ref values at call time. They never write secrets.
path "kv/data/*" {
  capabilities = ["read"]
}

path "transit/decrypt/veyntora" {
  capabilities = ["update"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
