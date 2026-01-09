"""
Velo Command Routing
"""
from typing import Dict, Any, Callable, TypeVar

T = TypeVar('T')

class CommandRouter:
    """Layer 2: Control Plane - Decorator-based command dispatching."""
    def __init__(self) -> None:
        self.handlers: Dict[str, Callable] = {}

    def handler(self, command_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.handlers[command_name] = func
            return func
        return decorator

    async def dispatch(self, server: Any, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch command to handler."""
        cmd_type = cmd.get("type", "Unknown")
        
        handler = self.handlers.get(cmd_type)
        if not handler:
            return {"type": "Error", "message": f"Unknown command: {cmd_type}"}
        
        try:
            return await handler(server, cmd)
        except Exception as e:
            import traceback
            return {"type": "Error", "message": f"Handler error: {str(e)}", "traceback": traceback.format_exc()}
