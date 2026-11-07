# Every Veyntora service reads its connection passwords (PostgreSQL, Valkey, S3, Keycloak)
# with this token when it starts (ADR 0034). Nothing else: provider and user keys stay
# readable only by the runtime token.
path "kv/data/veyntora/infra/*" {
  capabilities = ["read"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
