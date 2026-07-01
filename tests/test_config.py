"""
Config hygiene tests — no running stack required.

Validates:
  - .env.example contains every key referenced by docker-compose.yml
  - docker-compose.yml has no :latest image tags
  - .gitignore blocks files that must never be committed
"""

import re
from pathlib import Path

REPO = Path(__file__).parent.parent.resolve()

COMPOSE_FILE = REPO / "docker-compose.yml"
ENV_EXAMPLE = REPO / ".env.example"
GITIGNORE = REPO / ".gitignore"


# ── helpers ──────────────────────────────────────────────────────────────────

def _env_example_keys() -> set[str]:
    keys = set()
    for line in ENV_EXAMPLE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0])
    return keys


def _compose_text() -> str:
    return COMPOSE_FILE.read_text()


def _gitignore_text() -> str:
    return GITIGNORE.read_text()


# ── image pinning ─────────────────────────────────────────────────────────────

def test_no_latest_image_tags():
    """Every image in docker-compose.yml must be pinned to a specific version."""
    latest_images = []
    for line in _compose_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("image:") and stripped.endswith(":latest"):
            latest_images.append(stripped)
    assert latest_images == [], (
        "Found unpinned :latest image tags — pin each to a specific digest or version:\n"
        + "\n".join(f"  {img}" for img in latest_images)
    )


# ── env var coverage ──────────────────────────────────────────────────────────

def test_env_example_covers_compose_references():
    """
    Every ${VAR} reference in docker-compose.yml (without a :- default) should
    have a corresponding key in .env.example so operators know to set it.
    """
    # Match ${VAR} but not ${VAR:-default}
    bare_refs = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)(?!\:[^}])\}", _compose_text()))
    # Also collect ${VAR} without braces
    bare_refs |= set(re.findall(r"\$([A-Z_][A-Z0-9_]*)\b", _compose_text()))
    # Remove variables that are internal to Docker Compose or shell built-ins
    excluded = {"POSTGRES_USER", "POSTGRES_DB", "MINIO_ROOT_USER"}
    bare_refs -= excluded

    env_keys = _env_example_keys()
    missing = bare_refs - env_keys
    assert not missing, (
        "These vars are referenced in docker-compose.yml but missing from .env.example:\n"
        + "\n".join(f"  {v}" for v in sorted(missing))
    )


def test_env_example_has_no_vault_dev_token():
    """VAULT_DEV_ROOT_TOKEN_ID must not appear in .env.example — Vault runs in server mode."""
    assert "VAULT_DEV_ROOT_TOKEN_ID" not in ENV_EXAMPLE.read_text(), (
        "VAULT_DEV_ROOT_TOKEN_ID found in .env.example — remove it; "
        "it is a Vault dev-mode variable unused by the server-mode config."
    )


# ── .gitignore hygiene ────────────────────────────────────────────────────────

def test_gitignore_blocks_env():
    gitignore = _gitignore_text()
    assert ".env" in gitignore, ".env must be listed in .gitignore"


def test_gitignore_blocks_vault_init():
    gitignore = _gitignore_text()
    assert "vault-init.json" in gitignore, (
        "vault-init.json must be listed in .gitignore — it contains unseal keys"
    )


def test_gitignore_blocks_proxy_ca():
    gitignore = _gitignore_text()
    assert "docker/ca-bundle.crt" in gitignore, (
        "docker/ca-bundle.crt must be listed in .gitignore — never commit the proxy CA"
    )


# ── .env.example key completeness ─────────────────────────────────────────────

REQUIRED_KEYS = {
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "MINIO_KMS_SECRET_KEY",
    "KESTRA_ADMIN_USERNAME",
    "KESTRA_ADMIN_PASSWORD",
    "VAULT_TOKEN",
    "KEYCLOAK_ADMIN_PASSWORD",
    "GF_ADMIN_PASSWORD",
    "BVR_SERVICE_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
}


def test_env_example_has_required_keys():
    keys = _env_example_keys()
    missing = REQUIRED_KEYS - keys
    assert not missing, (
        ".env.example is missing required keys:\n"
        + "\n".join(f"  {k}" for k in sorted(missing))
    )
