# Local development only. Production (deploy/helm) runs a 3-node raft cluster with TLS,
# Kubernetes auth and auto-unseal; see docs/decisions/0004-secrets-write-only.md.
ui = false

storage "raft" {
  path    = "/openbao/file"
  node_id = "openbao-dev"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr     = "http://openbao:8200"
cluster_addr = "http://openbao:8201"
