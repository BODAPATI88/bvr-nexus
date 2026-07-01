"""
Tests for bvr_sdk.capability_matcher — CapabilityMatcher.

The Constitution YAML is written to a tempfile; no live filesystem dependency.
vault:// references are resolved from monkeypatched env vars.

conftest.py stubs `yaml` as an empty module, so we must restore the real yaml
and directly load capability_matcher.py before any test runs.
"""

import sys
import os
import textwrap
import importlib
import importlib.util
import pytest

# ---------------------------------------------------------------------------
# Load the real yaml (conftest stubs it) and capability_matcher directly.
# Must happen at import time so the module is available for all fixtures.
# ---------------------------------------------------------------------------

_SDK_ROOT = "/home/user/bvr-nexus/bvr-sdk"
if _SDK_ROOT not in sys.path:
    sys.path.insert(0, _SDK_ROOT)

# conftest.py already placed an empty stub in sys.modules["yaml"].
# Pop it so the real PyYAML is loaded when capability_matcher does `import yaml`.
sys.modules.pop("yaml", None)
import yaml as _real_yaml   # loads real PyYAML from disk
sys.modules["yaml"] = _real_yaml

_cm_spec = importlib.util.spec_from_file_location(
    "bvr_sdk.capability_matcher",
    f"{_SDK_ROOT}/bvr_sdk/capability_matcher.py",
)
_cm_mod = importlib.util.module_from_spec(_cm_spec)
sys.modules["bvr_sdk.capability_matcher"] = _cm_mod
_cm_spec.loader.exec_module(_cm_mod)

from bvr_sdk.capability_matcher import (  # type: ignore[import]
    CapabilityMatcher,
    CapabilityNotFound,
    NoHealthyProvider,
    get_matcher,
)

# ---------------------------------------------------------------------------
# Minimal constitution fixture
# ---------------------------------------------------------------------------

MINIMAL_CONSTITUTION = textwrap.dedent("""\
    schema: bvr.constitution.v1
    version: "2.0.0"
    defaults:
      selection_mode: priority
      fallback_enabled: true

    capabilities:
      code_analysis:
        description: "Analyze code"
        version: "1.0.0"
        required_permissions: ["code:read"]
        sla:
          max_duration_ms: 30000
        providers:
          - id: claude_code
            name: "Claude Code Analysis"
            plugin_id: "ai/claude"
            priority: 1
            selection:
              fallback_enabled: true
            config:
              api_key: "vault://secrets/anthropic/api_key"
            cost:
              per_token: 0.000015

          - id: gpt_code
            name: "GPT Code Analysis"
            plugin_id: "ai/openai"
            priority: 2
            selection:
              fallback_enabled: true
            config:
              api_key: "vault://secrets/openai/api_key"
            cost:
              per_token: 0.000010

          - id: ollama_code
            name: "Ollama Local"
            plugin_id: "ai/ollama"
            priority: 3
            selection:
              fallback_enabled: false
            config:
              base_url: "http://ollama:11434"
            cost:
              per_token: 0.0

      clone_repository:
        description: "Clone a git repo"
        version: "1.0.0"
        required_permissions: ["code:read"]
        sla:
          max_duration_ms: 60000
        providers:
          - id: github_clone
            name: "GitHub Clone"
            plugin_id: "code/github"
            priority: 1
            selection:
              fallback_enabled: true
            config:
              token: "vault://secrets/github/token"
            cost:
              per_request: 0.0

    workflow_overrides:
      bvr.achieve.resume-optimization:
        code_analysis:
          providers:
            - id: gpt_code
              priority: 1
            - id: claude_code
              priority: 2
""")


def _make_matcher(constitution_path: str) -> CapabilityMatcher:
    """Build a CapabilityMatcher pointed at a specific constitution file."""
    m = CapabilityMatcher.__new__(CapabilityMatcher)
    m._capabilities = {}
    m._provider_health = {}

    import bvr_sdk.capability_matcher as cm
    original = cm.CONSTITUTION_PATH
    cm.CONSTITUTION_PATH = type(cm.CONSTITUTION_PATH)(constitution_path)
    m._load_constitution()
    cm.CONSTITUTION_PATH = original
    return m


@pytest.fixture()
def matcher(tmp_path):
    """Return a CapabilityMatcher loaded from the minimal constitution."""
    # Reset global singleton
    import bvr_sdk.capability_matcher as cm
    cm._matcher = None

    f = tmp_path / "constitution.yaml"
    f.write_text(MINIMAL_CONSTITUTION)
    return _make_matcher(str(f))


# ---------------------------------------------------------------------------
# Loading and basic structure
# ---------------------------------------------------------------------------

class TestConstitutionLoading:
    def test_capabilities_loaded(self, matcher):
        caps = matcher.list_capabilities()
        ids = [c["id"] for c in caps]
        assert "code_analysis" in ids
        assert "clone_repository" in ids

    def test_provider_count(self, matcher):
        caps = {c["id"]: c for c in matcher.list_capabilities()}
        assert caps["code_analysis"]["provider_count"] == 3
        assert caps["clone_repository"]["provider_count"] == 1

    def test_missing_constitution_raises(self, tmp_path):
        import bvr_sdk.capability_matcher as cm
        original = cm.CONSTITUTION_PATH
        cm.CONSTITUTION_PATH = type(cm.CONSTITUTION_PATH)(tmp_path / "nonexistent.yaml")
        try:
            with pytest.raises(RuntimeError, match="Constitution not found"):
                CapabilityMatcher()
        finally:
            cm.CONSTITUTION_PATH = original


# ---------------------------------------------------------------------------
# resolve() — happy path
# ---------------------------------------------------------------------------

class TestResolve:
    def test_resolve_returns_highest_priority_provider(self, matcher):
        provider = matcher.resolve("code_analysis")
        assert provider.id == "claude_code"

    def test_resolve_clone_repository(self, matcher):
        provider = matcher.resolve("clone_repository")
        assert provider.plugin_id == "code/github"

    def test_resolve_skips_unhealthy_provider(self, matcher):
        matcher.update_health("claude_code", healthy=False)
        provider = matcher.resolve("code_analysis")
        assert provider.id == "gpt_code"

    def test_resolve_with_preferred_provider(self, matcher):
        provider = matcher.resolve("code_analysis", preferred_provider="gpt_code")
        assert provider.id == "gpt_code"

    def test_resolve_preferred_falls_through_when_unhealthy(self, matcher):
        matcher.update_health("gpt_code", healthy=False)
        provider = matcher.resolve("code_analysis", preferred_provider="gpt_code")
        assert provider.id == "claude_code"


# ---------------------------------------------------------------------------
# resolve() — error cases
# ---------------------------------------------------------------------------

class TestResolveErrors:
    def test_unknown_capability_raises_capability_not_found(self, matcher):
        with pytest.raises(CapabilityNotFound, match="document_analysis"):
            matcher.resolve("document_analysis")

    def test_all_providers_unhealthy_raises_no_healthy_provider(self, matcher):
        matcher.update_health("claude_code", healthy=False)
        matcher.update_health("gpt_code", healthy=False)
        matcher.update_health("ollama_code", healthy=False)
        with pytest.raises(NoHealthyProvider, match="code_analysis"):
            matcher.resolve("code_analysis")


# ---------------------------------------------------------------------------
# resolve_with_fallback()
# ---------------------------------------------------------------------------

class TestResolveWithFallback:
    def test_returns_only_fallback_enabled_providers(self, matcher):
        providers = matcher.resolve_with_fallback("code_analysis")
        ids = [p.id for p in providers]
        assert "ollama_code" not in ids   # fallback_enabled: false
        assert "claude_code" in ids
        assert "gpt_code" in ids

    def test_returns_in_priority_order(self, matcher):
        providers = matcher.resolve_with_fallback("code_analysis")
        priorities = [p.priority for p in providers]
        assert priorities == sorted(priorities)

    def test_excludes_unhealthy_from_fallback_list(self, matcher):
        matcher.update_health("claude_code", healthy=False)
        providers = matcher.resolve_with_fallback("code_analysis")
        ids = [p.id for p in providers]
        assert "claude_code" not in ids


# ---------------------------------------------------------------------------
# Workflow overrides
# ---------------------------------------------------------------------------

class TestWorkflowOverrides:
    def test_resume_optimization_prefers_gpt(self, matcher):
        provider = matcher.resolve(
            "code_analysis",
            workflow_id="bvr.achieve.resume-optimization"
        )
        assert provider.id == "gpt_code"

    def test_no_override_uses_default_priority(self, matcher):
        provider = matcher.resolve(
            "code_analysis",
            workflow_id="bvr.review.repository"
        )
        assert provider.id == "claude_code"

    def test_unknown_workflow_uses_default_priority(self, matcher):
        provider = matcher.resolve(
            "code_analysis",
            workflow_id="bvr.nonexistent.workflow"
        )
        assert provider.id == "claude_code"


# ---------------------------------------------------------------------------
# vault:// reference resolution
# ---------------------------------------------------------------------------

class TestVaultResolution:
    def test_vault_ref_resolved_from_env(self, matcher, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-1234")
        config = matcher.get_provider_config("claude_code")
        assert config["api_key"] == "sk-test-1234"

    def test_vault_ref_kept_when_env_missing(self, matcher, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = matcher.get_provider_config("claude_code")
        assert config["api_key"].startswith("vault://")

    def test_non_vault_config_passed_through(self, matcher):
        config = matcher.get_provider_config("ollama_code")
        assert config["base_url"] == "http://ollama:11434"

    def test_unknown_provider_returns_empty_dict(self, matcher):
        config = matcher.get_provider_config("nonexistent_provider_xyz")
        assert config == {}


# ---------------------------------------------------------------------------
# update_health()
# ---------------------------------------------------------------------------

class TestUpdateHealth:
    def test_mark_provider_unhealthy(self, matcher):
        matcher.update_health("claude_code", healthy=False)
        provider = matcher.resolve("code_analysis")
        assert provider.id != "claude_code"

    def test_mark_provider_healthy_again(self, matcher):
        matcher.update_health("claude_code", healthy=False)
        matcher.update_health("claude_code", healthy=True)
        provider = matcher.resolve("code_analysis")
        assert provider.id == "claude_code"

    def test_update_health_unknown_provider_is_noop(self, matcher):
        matcher.update_health("does_not_exist", healthy=False)  # must not raise
