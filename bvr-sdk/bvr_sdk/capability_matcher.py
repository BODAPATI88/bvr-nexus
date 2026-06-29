"""
BVR Capability Matcher — Option A Implementation
Reads the Constitution at boot, selects providers statically.
No runtime surprises. YAML-driven, predictable, fast.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

CONSTITUTION_PATH = Path(os.getenv("BVR_CONSTITUTION", "/app/contracts/constitution.yaml"))

@dataclass
class Provider:
    id: str
    name: str
    plugin_id: str
    priority: int
    fallback_enabled: bool
    config: Dict[str, Any]
    cost: Dict[str, float]
    constraints: Dict[str, Any]
    healthy: bool = True  # Updated by health checker

@dataclass  
class Capability:
    id: str
    name: str
    description: str
    version: str
    providers: List[Provider]
    sla: Dict[str, Any]
    required_permissions: List[str]

class CapabilityMatcher:
    """
    The Capability Matcher reads the Constitution at boot
    and maintains an in-memory registry of all capabilities
    and their providers, ordered by priority.

    When a workflow requests a capability, it returns the
    highest-priority healthy provider. No runtime computation.
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._provider_health: Dict[str, bool] = {}
        self._load_constitution()

    def _load_constitution(self):
        """Load and parse the Constitution YAML at boot time."""
        if not CONSTITUTION_PATH.exists():
            raise RuntimeError(f"Constitution not found: {CONSTITUTION_PATH}")

        with open(CONSTITUTION_PATH) as f:
            constitution = yaml.safe_load(f)

        defaults = constitution.get("defaults", {})

        for cap_id, cap_data in constitution.get("capabilities", {}).items():
            providers = []
            for prov_data in cap_data.get("providers", []):
                provider = Provider(
                    id=prov_data["id"],
                    name=prov_data["name"],
                    plugin_id=prov_data["plugin_id"],
                    priority=prov_data.get("priority", 999),
                    fallback_enabled=prov_data.get("selection", {}).get("fallback_enabled", True),
                    config=prov_data.get("config", {}),
                    cost=prov_data.get("cost", {}),
                    constraints=prov_data.get("constraints", {}),
                )
                providers.append(provider)

            # Sort by priority (lower number = higher priority)
            providers.sort(key=lambda p: p.priority)

            self._capabilities[cap_id] = Capability(
                id=cap_id,
                name=cap_data.get("name", cap_id),
                description=cap_data.get("description", ""),
                version=cap_data.get("version", "1.0.0"),
                providers=providers,
                sla=cap_data.get("sla", {}),
                required_permissions=cap_data.get("required_permissions", [])
            )

        self._constitution_raw = constitution  # cached — no repeated YAML parsing
        print(f"[MATCHER] Loaded {len(self._capabilities)} capabilities from Constitution")

    def resolve(
        self,
        capability_id: str,
        workflow_id: Optional[str] = None,
        preferred_provider: Optional[str] = None
    ) -> Provider:
        """
        Resolve a capability to a provider.

        Args:
            capability_id: The capability to resolve (e.g., "web_search")
            workflow_id: Optional workflow for per-workflow overrides
            preferred_provider: Optional explicit provider preference

        Returns:
            The selected Provider

        Raises:
            CapabilityNotFound: If capability doesn't exist
            NoHealthyProvider: If no provider is healthy
        """
        capability = self._capabilities.get(capability_id)
        if not capability:
            raise CapabilityNotFound(f"Capability not found: {capability_id}")

        # Apply workflow overrides if specified
        providers = self._apply_workflow_override(capability_id, workflow_id)

        # If preferred provider specified, try it first
        if preferred_provider:
            for provider in providers:
                if provider.id == preferred_provider and provider.healthy:
                    return provider
            # Preferred provider not healthy, fall through to priority list

        # Walk priority list, return first healthy provider
        for provider in providers:
            if provider.healthy:
                return provider

        # No healthy providers
        raise NoHealthyProvider(
            f"No healthy providers for capability: {capability_id}. "
            f"Checked: {[p.id for p in providers]}"
        )

    def resolve_with_fallback(
        self,
        capability_id: str,
        workflow_id: Optional[str] = None
    ) -> List[Provider]:
        """
        Resolve a capability to an ordered list of providers.
        Returns all fallback-enabled providers in priority order.
        Used by the AI Gateway for cascading fallback.
        """
        capability = self._capabilities.get(capability_id)
        if not capability:
            raise CapabilityNotFound(f"Capability not found: {capability_id}")

        providers = self._apply_workflow_override(capability_id, workflow_id)

        # Return all healthy, fallback-enabled providers
        return [p for p in providers if p.healthy and p.fallback_enabled]

    def _apply_workflow_override(
        self,
        capability_id: str,
        workflow_id: Optional[str]
    ) -> List[Provider]:
        """Apply per-workflow priority overrides from the Constitution."""
        capability = self._capabilities[capability_id]
        providers = list(capability.providers)  # Copy

        if not workflow_id:
            return providers

        # Use Constitution cached at boot — no repeated file IO
        constitution = self._constitution_raw
        overrides = constitution.get("workflow_overrides", {}).get(workflow_id, {}).get(capability_id, {})

        if not overrides:
            return providers

        # Apply priority overrides
        override_providers = overrides.get("providers", [])
        override_map = {p["id"]: p["priority"] for p in override_providers}

        for provider in providers:
            if provider.id in override_map:
                provider.priority = override_map[provider.id]

        # Re-sort by new priorities
        providers.sort(key=lambda p: p.priority)

        return providers

    def update_health(self, provider_id: str, healthy: bool):
        """Update health status of a provider (called by health checker)."""
        for capability in self._capabilities.values():
            for provider in capability.providers:
                if provider.id == provider_id:
                    provider.healthy = healthy
                    status = "healthy" if healthy else "unhealthy"
                    print(f"[MATCHER] Provider {provider_id} is now {status}")
                    return

    def list_capabilities(self) -> List[Dict[str, Any]]:
        """List all registered capabilities."""
        return [
            {
                "id": cap.id,
                "name": cap.name,
                "description": cap.description,
                "version": cap.version,
                "provider_count": len(cap.providers),
                "healthy_providers": sum(1 for p in cap.providers if p.healthy),
                "required_permissions": cap.required_permissions,
            }
            for cap in self._capabilities.values()
        ]

    def get_provider_config(self, provider_id: str) -> Dict[str, Any]:
        """Get configuration for a specific provider."""
        for capability in self._capabilities.values():
            for provider in capability.providers:
                if provider.id == provider_id:
                    return provider.config
        return {}

class CapabilityNotFound(Exception):
    pass

class NoHealthyProvider(Exception):
    pass

# Global singleton instance
_matcher: Optional[CapabilityMatcher] = None

def get_matcher() -> CapabilityMatcher:
    """Get or create the global Capability Matcher."""
    global _matcher
    if _matcher is None:
        _matcher = CapabilityMatcher()
    return _matcher
