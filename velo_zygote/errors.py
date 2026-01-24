"""
Velo Custom Exceptions for H-Gov (RFC-0012)
"""

from typing import Any


class VeloBaseError(Exception):
    """Base class for all Velo-specific errors."""

    pass


class VeloOptimizationError(VeloBaseError):
    """
    Exception raised when a mandatory optimization fails.
    This triggers the H-Gov backtunnel to report the failure to the Rust supervisor.
    """

    def __init__(self, message: str, optimization_id: str, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.optimization_id = optimization_id
        self.context = context or {}

    def to_msgpack(self) -> bytes:
        """
        RFC-0012 Phase 11.0: Serialize error for H-Gov backtunnel.
        Enables Python-side errors to be transmitted to Rust GovernanceSignal.
        """
        import time

        import msgpack

        signal = {
            "type": "VeloOptimizationError",
            "optimization_id": self.optimization_id,
            "message": str(self),
            "context": self.context,
            "timestamp_ns": int(time.time() * 1_000_000_000),
        }
        return bytes(msgpack.packb(signal))

    @classmethod
    def from_msgpack(cls, data: bytes) -> "VeloOptimizationError":
        """Deserialize H-Gov signal from MessagePack."""
        import msgpack

        signal = msgpack.unpackb(data, raw=False)
        return cls(
            message=signal.get("message", "Unknown error"),
            optimization_id=signal.get("optimization_id", "UNKNOWN"),
            context=signal.get("context", {}),
        )


class VeloSecurityViolation(VeloBaseError):
    """Exception raised for security policy violations in the sandbox."""

    pass
