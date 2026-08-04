from typing import Dict, List, Type
from adapters.base import SupplierAdapter
from adapters.atlas_adapter import AtlasAdapter
from adapters.nova_adapter import NovaAdapter
from adapters.exceptions import SupplierNotFoundError


class AdapterRegistry:
    """
    Registry for managing and fetching active supplier adapter instances.
    
    Adding a new supplier requires:
    1. Implementing a new SupplierAdapter subclass (e.g. AcmeAdapter)
    2. Registering it via `registry.register(AcmeAdapter())`
    """

    def __init__(self):
        self._adapters: Dict[str, SupplierAdapter] = {}

    def register(self, adapter: SupplierAdapter) -> None:
        """Register an adapter instance by its supplier_id."""
        self._adapters[adapter.supplier_id.lower()] = adapter

    def get(self, supplier_id: str) -> SupplierAdapter:
        """Retrieve a registered adapter instance by supplier_id."""
        normalized_id = supplier_id.lower()
        if normalized_id not in self._adapters:
            raise SupplierNotFoundError(
                f"No adapter registered for supplier '{supplier_id}'. Registered suppliers: {self.list_suppliers()}",
                supplier_id=supplier_id
            )
        return self._adapters[normalized_id]

    def list_suppliers(self) -> List[str]:
        """List all currently registered supplier IDs."""
        return list(self._adapters.keys())

    def clear(self) -> None:
        """Reset all registered adapters."""
        self._adapters.clear()


# Default global registry instance prepopulated with built-in adapters
registry = AdapterRegistry()
registry.register(AtlasAdapter())
registry.register(NovaAdapter())


def get_adapter(supplier_id: str) -> SupplierAdapter:
    """Convenience function to get adapter from default registry."""
    return registry.get(supplier_id)


def register_adapter(adapter: SupplierAdapter) -> None:
    """Convenience function to register an adapter in default registry."""
    registry.register(adapter)
