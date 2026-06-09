from abc import ABC, abstractmethod
from typing import Any, Dict


class ConnectorBase(ABC):
    """Each connector receives resolved config + tool_inputs and returns a result dict."""

    @abstractmethod
    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the connector action. Returns a JSON-serialisable dict."""
        ...

    @property
    @abstractmethod
    def actions(self) -> list[str]:
        """List of action names this connector supports (for UI display)."""
        ...
