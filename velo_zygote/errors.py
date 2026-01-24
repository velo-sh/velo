"""
Velo Custom Exceptions for H-Gov (RFC-0012)
"""


from typing import Any, Optional


class VeloBaseError(Exception):
    """Base class for all Velo-specific errors."""

    pass


class VeloOptimizationError(VeloBaseError):
    """
    Exception raised when a mandatory optimization fails.
    This triggers the H-Gov backtunnel to report the failure to the Rust supervisor.
    """

    def __init__(self, message: str, optimization_id: str, context: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.optimization_id = optimization_id
        self.context = context or {}



class VeloSecurityViolation(VeloBaseError):
    """Exception raised for security policy violations in the sandbox."""

    pass
