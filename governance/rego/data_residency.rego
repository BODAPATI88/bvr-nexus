package bvr.data

import future.keywords.if

# ── Data Residency ──
allowed_regions := ["us-east-1", "eu-west-1", "ap-south-1"]

region_allowed if {
    allowed_regions[_] == input.region
}

# ── PII Handling ──
no_pii_exposure if {
    not input.contains_pii
}

# ── Data Classification ──
allowed_classifications := ["public", "internal", "confidential"]

classification_allowed if {
    allowed_classifications[_] == input.classification
}
