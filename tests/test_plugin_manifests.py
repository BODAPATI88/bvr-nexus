"""
Plugin manifest validation — no running stack required.

Validates that every plugin directory under plugins/ has:
  - manifest.yaml with required fields (id, name, version, type, capabilities)
  - schema.yaml
  - permissions.yaml
  - health.py
  - worker.py
"""

import json
import re
import sys
from pathlib import Path

# The shared conftest replaces 'yaml' with an empty stub so that SDK modules
# that import yaml don't crash. We need the real PyYAML here, so we remove the
# stub and import the real package before any test function runs.
if "yaml" in sys.modules and not hasattr(sys.modules["yaml"], "safe_load"):
    del sys.modules["yaml"]
import yaml  # noqa: E402  (real PyYAML, not the conftest stub)

REPO_ROOT = Path(__file__).parent.parent.resolve()
PLUGINS_DIR = REPO_ROOT / "plugins"
DASHBOARDS_DIR = REPO_ROOT / "observability" / "dashboards"

REQUIRED_MANIFEST_KEYS = {"id", "name", "version", "type", "capabilities"}
REQUIRED_PLUGIN_FILES = {"schema.yaml", "permissions.yaml", "health.py", "worker.py"}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _all_plugin_manifests() -> list[Path]:
    """Return all manifest.yaml paths found under plugins/."""
    return sorted(PLUGINS_DIR.rglob("manifest.yaml"))


def _load_manifest(path: Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_plugin_dirs_have_manifest():
    """Every plugin directory discovered under plugins/ must have a manifest.yaml
    that parses successfully and contains the required top-level keys."""
    manifests = _all_plugin_manifests()
    assert manifests, "No manifest.yaml files found under plugins/ — check PLUGINS_DIR path"

    missing_keys: dict[str, set] = {}
    for path in manifests:
        data = _load_manifest(path)
        absent = REQUIRED_MANIFEST_KEYS - data.keys()
        if absent:
            missing_keys[str(path.relative_to(REPO_ROOT))] = absent

    assert not missing_keys, (
        "The following manifests are missing required keys:\n"
        + "\n".join(f"  {p}: {sorted(k)}" for p, k in missing_keys.items())
    )


def test_all_plugin_dirs_have_required_files():
    """Every plugin directory that contains a manifest.yaml must also contain
    schema.yaml, permissions.yaml, health.py, and worker.py."""
    missing: dict[str, list[str]] = {}
    for manifest_path in _all_plugin_manifests():
        plugin_dir = manifest_path.parent
        absent = [f for f in sorted(REQUIRED_PLUGIN_FILES) if not (plugin_dir / f).exists()]
        if absent:
            missing[str(plugin_dir.relative_to(REPO_ROOT))] = absent

    assert not missing, (
        "The following plugin directories are missing required files:\n"
        + "\n".join(f"  {p}: {files}" for p, files in missing.items())
    )


def test_manifest_capabilities_is_list():
    """The 'capabilities' field in every manifest must be a non-empty list."""
    violations: list[str] = []
    for path in _all_plugin_manifests():
        data = _load_manifest(path)
        caps = data.get("capabilities")
        if not isinstance(caps, list) or len(caps) == 0:
            violations.append(str(path.relative_to(REPO_ROOT)))

    assert not violations, (
        "The following manifests have an empty or non-list 'capabilities' field:\n"
        + "\n".join(f"  {p}" for p in violations)
    )


def test_manifest_version_is_semver():
    """The 'version' field in every manifest must match MAJOR.MINOR.PATCH."""
    violations: list[str] = []
    for path in _all_plugin_manifests():
        data = _load_manifest(path)
        version = str(data.get("version", ""))
        if not SEMVER_RE.match(version):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {version!r}")

    assert not violations, (
        "The following manifests have a non-semver 'version' field:\n"
        + "\n".join(f"  {p}" for p in violations)
    )


def test_grafana_provisioning_yaml_exists():
    """observability/dashboards/provisioning.yaml must exist and parse as valid YAML."""
    prov = DASHBOARDS_DIR / "provisioning.yaml"
    assert prov.exists(), f"Missing Grafana provisioning file: {prov}"
    with prov.open() as fh:
        data = yaml.safe_load(fh)
    assert data is not None, "provisioning.yaml parsed as empty/null"
    assert "providers" in data, "provisioning.yaml missing 'providers' key"


def test_grafana_dashboard_json_is_valid():
    """observability/dashboards/bvr-overview.json must exist, parse as JSON,
    and contain the required top-level keys: uid, title, panels."""
    dash = DASHBOARDS_DIR / "bvr-overview.json"
    assert dash.exists(), f"Missing Grafana dashboard file: {dash}"
    with dash.open() as fh:
        data = json.load(fh)
    for key in ("uid", "title", "panels"):
        assert key in data, f"bvr-overview.json missing required key: '{key}'"
    assert isinstance(data["panels"], list) and len(data["panels"]) > 0, (
        "bvr-overview.json 'panels' must be a non-empty list"
    )
