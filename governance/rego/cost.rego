package bvr.cost

import future.keywords.if
import future.keywords.in

# ── Cost Guardrails ──
max_cost_per_execution := 5.00  # $5 USD
max_cost_per_day := 50.00       # $50 USD per user per day
max_tokens_per_execution := 100000

cost_allowed if {
    input.estimated_cost <= max_cost_per_execution
}

daily_cost_allowed if {
    input.daily_cost <= max_cost_per_day
}

tokens_allowed if {
    input.estimated_tokens <= max_tokens_per_execution
}

# ── Provider Restrictions ──
allowed_providers := ["claude", "gpt", "kimi", "ollama"]

provider_allowed if {
    input.provider in allowed_providers
}

# ── Local Model Preference for Sensitive Data ──
require_local_for_pii if {
    input.contains_pii
    input.provider == "ollama"
}
