# Vault Production Configuration
# Run: vault operator init → vault operator unseal (x3)
# Then: ./scripts/setup_vault.sh

storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true  # Enable TLS in production with cert_file/key_file
}

api_addr = "http://vault:8200"
cluster_addr = "http://vault:8201"

ui = true
