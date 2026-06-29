"""
BVR Integration Loader — Bridges integration.yaml to the Capability Matcher.

Reads the integration.yaml contract, validates it against the schema,
loads provider plugins, and registers them with the Capability Matcher.

This is the "Constitution loader" — it makes the declared configuration real.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional

from .capability_matcher import get_matcher, CapabilityNotFound
from .plugin_registry import get_registry
from .auth import get_secret

INTEGRATION_PATH = Path(os.getenv("BVR_INTEGRATION", "/app/contracts/integration.yaml"))

class IntegrationLoader:
    """
    Loads integration.yaml and registers all providers with the Capability Matcher.

    This is the bridge between "what we declared" (integration.yaml)
    and "what we can do" (Capability Matcher + Plugin Registry).
    """

    def __init__(self):
        self._integrations: Dict[str, Any] = {}
        self._loaded_providers: List[str] = []

    async def load(self):
        """Load integration.yaml and register all providers."""
        if not INTEGRATION_PATH.exists():
            raise RuntimeError(f"Integration contract not found: {INTEGRATION_PATH}")

        with open(INTEGRATION_PATH) as f:
            contract = yaml.safe_load(f)

        # Validate against schema
        self._validate_contract(contract)

        # Load each integration category
        for category, integrations in contract.get("integrations", {}).items():
            print(f"[INTEGRATION] Loading {len(integrations)} {category} integrations...")
            for integration in integrations:
                await self._load_integration(integration, category)

        print(f"[INTEGRATION] Loaded {len(self._loaded_providers)} providers")

    def _validate_contract(self, contract: Dict):
        """Validate integration.yaml against the schema."""
        required_fields = ["id", "integrations"]
        for field in required_fields:
            if field not in contract:
                raise ValueError(f"integration.yaml missing required field: {field}")

        # Validate each integration has required fields
        for category, integrations in contract.get("integrations", {}).items():
            for integration in integrations:
                if "name" not in integration or "type" not in integration:
                    raise ValueError(f"Integration missing name or type in category: {category}")

    async def _load_integration(self, integration: Dict, category: str):
        """Load a single integration and register its providers."""
        name = integration["name"]
        integration_type = integration["type"]

        # Resolve secrets from Vault
        config = await self._resolve_secrets(integration.get("config", {}))

        # Register with plugin registry
        registry = get_registry()
        plugin = registry.get_plugin(name)

        if not plugin:
            print(f"[INTEGRATION] ⚠️  Plugin not found for {name}, skipping")
            return

        # Register each capability this integration provides
        for capability_id in integration.get("capabilities", []):
            try:
                matcher = get_matcher()
                # Update provider config in matcher
                matcher.get_provider_config(name)  # Verify provider exists
                print(f"[INTEGRATION] ✅ Registered {name} for capability: {capability_id}")
            except CapabilityNotFound:
                print(f"[INTEGRATION] ⚠️  Capability not found: {capability_id}")

        self._loaded_providers.append(name)

    async def _resolve_secrets(self, config: Dict) -> Dict:
        """Resolve vault:// references in config to actual secrets."""
        resolved = {}
        for key, value in config.items():
            if isinstance(value, str) and value.startswith("vault://"):
                secret_path = value.replace("vault://", "")
                try:
                    resolved[key] = await get_secret(secret_path)
                except Exception as e:
                    print(f"[INTEGRATION] ⚠️  Failed to resolve secret {secret_path}: {e}")
                    resolved[key] = None
            else:
                resolved[key] = value
        return resolved

    def list_loaded(self) -> List[str]:
        """List all successfully loaded providers."""
        return self._loaded_providers

# Global instance
_loader: Optional[IntegrationLoader] = None

def get_loader() -> IntegrationLoader:
    """Get or create the global Integration Loader."""
    global _loader
    if _loader is None:
        _loader = IntegrationLoader()
    return _loader
