"""
Real Plugin Auto-Discovery — Scans plugin directories, parses manifests,
registers capabilities. Not manual load-by-ID.
"""

import hashlib
import os
import yaml
import importlib.util
from pathlib import Path
from typing import Dict, List, Any, Optional


def _verify_plugin_manifest(plugin_dir: str, plugin_id: str) -> None:
    """Verify plugin manifest integrity via SHA256 before loading plugin code.

    Always logs the manifest SHA256 for audit purposes. If the manifest
    declares a ``manifest_sha256`` field, the computed hash must match or
    loading is aborted with a RuntimeError.
    """
    manifest_path = os.path.join(plugin_dir, "manifest.yaml")
    if not os.path.exists(manifest_path):
        raise RuntimeError(f"Plugin {plugin_id}: missing manifest.yaml")
    raw = open(manifest_path, "rb").read()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    print(f"[PLUGIN] {plugin_id} manifest SHA256: {actual_sha256}")
    try:
        manifest = yaml.safe_load(raw)
        expected = manifest.get("manifest_sha256")
        if expected and expected != actual_sha256:
            raise RuntimeError(
                f"Plugin {plugin_id}: manifest SHA256 mismatch "
                f"(expected {expected}, got {actual_sha256})"
            )
    except Exception as exc:
        if "mismatch" in str(exc):
            raise
        # yaml not available or parse error — log and continue
        print(f"[PLUGIN] {plugin_id}: manifest verification skipped ({exc})")

PLUGINS_DIR = Path(os.getenv("BVR_PLUGINS_DIR", "/app/plugins"))

class PluginRegistry:
    """Auto-discovers and registers all plugins."""

    def __init__(self):
        self._plugins: Dict[str, Dict[str, Any]] = {}
        self._discover()

    def _discover(self):
        """Scan all plugin directories and load manifests."""
        if not PLUGINS_DIR.exists():
            print(f"[PLUGIN] Plugins directory not found: {PLUGINS_DIR}")
            return

        for category_dir in PLUGINS_DIR.iterdir():
            if not category_dir.is_dir():
                continue

            for plugin_dir in category_dir.iterdir():
                if not plugin_dir.is_dir():
                    continue

                manifest_path = plugin_dir / "manifest.yaml"
                if not manifest_path.exists():
                    print(f"[PLUGIN] Skip {plugin_dir.name}: no manifest.yaml")
                    continue

                try:
                    with open(manifest_path) as f:
                        manifest = yaml.safe_load(f)

                    plugin_id = manifest.get("id", plugin_dir.name)

                    # Validate required fields
                    if not all(k in manifest for k in ["id", "name", "version", "type"]):
                        print(f"[PLUGIN] Skip {plugin_id}: missing required fields")
                        continue

                    # Load schema if exists
                    schema_path = plugin_dir / "schema.yaml"
                    schema = None
                    if schema_path.exists():
                        with open(schema_path) as f:
                            schema = yaml.safe_load(f)

                    # Load permissions if exists
                    permissions_path = plugin_dir / "permissions.yaml"
                    permissions = None
                    if permissions_path.exists():
                        with open(permissions_path) as f:
                            permissions = yaml.safe_load(f)

                    # Verify manifest integrity before executing any plugin code
                    _verify_plugin_manifest(str(plugin_dir), plugin_id)

                    # Load health check module
                    health_module = None
                    health_path = plugin_dir / "health.py"
                    if health_path.exists():
                        spec = importlib.util.spec_from_file_location(
                            f"{plugin_id}.health", health_path
                        )
                        health_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(health_module)

                    # Load worker module
                    worker_module = None
                    worker_path = plugin_dir / "worker.py"
                    if worker_path.exists():
                        spec = importlib.util.spec_from_file_location(
                            f"{plugin_id}.worker", worker_path
                        )
                        worker_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(worker_module)

                    entry = {
                        "manifest": manifest,
                        "schema": schema,
                        "permissions": permissions,
                        "health_module": health_module,
                        "worker_module": worker_module,
                        "path": str(plugin_dir),
                        "category": category_dir.name,
                    }
                    self._plugins[plugin_id] = entry
                    # Also register by category/id path so constitution plugin_id refs resolve
                    self._plugins[f"{category_dir.name}/{plugin_id}"] = entry

                    print(f"[PLUGIN] Registered: {plugin_id} ({manifest['name']} v{manifest['version']})")

                except Exception as e:
                    print(f"[PLUGIN] Error loading {plugin_dir.name}: {e}")

    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all discovered plugins."""
        return [
            {
                "id": pid,
                "name": p["manifest"]["name"],
                "version": p["manifest"]["version"],
                "type": p["manifest"]["type"],
                "category": p["category"],
                "capabilities": p["manifest"].get("capabilities", []),
                "status": "active",
            }
            for pid, p in self._plugins.items()
        ]

    def get_plugin(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """Get a plugin by ID."""
        return self._plugins.get(plugin_id)

    def find_by_capability(self, capability: str) -> List[Dict[str, Any]]:
        """Find all plugins that provide a capability."""
        results = []
        for pid, p in self._plugins.items():
            caps = p["manifest"].get("capabilities", [])
            if capability in caps:
                results.append({
                    "id": pid,
                    "name": p["manifest"]["name"],
                    "priority": p["manifest"].get("priority", 999),
                })
        return sorted(results, key=lambda x: x["priority"])

    async def health_check(self, plugin_id: str, config: dict) -> dict:
        """Run health check for a plugin."""
        plugin = self._plugins.get(plugin_id)
        if not plugin or not plugin["health_module"]:
            return {"status": "unknown", "reason": "no health module"}

        try:
            health_func = getattr(plugin["health_module"], "health_check")
            return await health_func(config)
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def execute(self, plugin_id: str, config: dict, inputs: dict) -> dict:
        """Execute a plugin worker."""
        plugin = self._plugins.get(plugin_id)
        if not plugin or not plugin["worker_module"]:
            raise ValueError(f"Plugin not found or no worker: {plugin_id}")

        execute_func = getattr(plugin["worker_module"], "execute")
        return await execute_func(config, inputs)

# Global registry instance
_plugin_registry: Optional[PluginRegistry] = None

def get_registry() -> PluginRegistry:
    """Get or create the global plugin registry."""
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry
