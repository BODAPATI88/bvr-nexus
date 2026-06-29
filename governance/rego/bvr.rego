package bvr

import future.keywords.if
import future.keywords.in

# ── Default Deny ──
default allow := false

# ── Allow if all conditions met ──
allow if {
    input.action in ["review", "architect", "research", "achieve"]
    user_has_role(input.user, "bvr-operator")
    target_allowed(input.action, input.target)
    rate_limit_ok(input.user)
}

# ── Admin Override ──
allow if {
    user_has_role(input.user, "bvr-admin")
}

# ── Role Definitions (would be fetched from Keycloak/Vault in production) ──
user_has_role(user, role) if {
    roles := data.bvr.users[user].roles
    role in roles
}

# ── Target Allowlist ──
target_allowed("review", target) if {
    not startswith(target, "file:///etc")
    not startswith(target, "file:///root")
}

target_allowed("architect", _) := true
target_allowed("research", _) := true
target_allowed("achieve", _) := true

# ── Rate Limiting (simplified) ──
rate_limit_ok(user) if {
    count := data.bvr.rate_limits[user].request_count
    count < 100  # 100 requests per window
}

# ── Cost Guardrails ──
max_cost_per_execution := 5.00  # $5 USD

cost_allowed if {
    input.estimated_cost <= max_cost_per_execution
}

# ── Compliance: Data Residency ──
allowed_region(region) if {
    region in ["us-east-1", "eu-west-1", "ap-south-1"]
}

# ── Compliance: PII Handling ──
no_pii_exposure if {
    not input.contains_pii
}
