"""
Velo Utilities
"""
import os
import time
try:
    from .settings import velo_config
except (ImportError, ValueError):
    from settings import velo_config

class ForkRateLimiter:
    """RFC-0011 WB-005: Token bucket rate limiter for Fork DoS protection."""
    
    def __init__(self, max_tokens: int = 100, refill_interval_ms: int = 50):
        self.max_tokens = max_tokens
        self.refill_interval_ms = refill_interval_ms / 1000.0  # Convert to seconds
        self.tokens = max_tokens
        self.last_refill = time.time()
        self._disabled = velo_config.is_ci or os.environ.get("VELO_RATE_LIMIT_DISABLED") == "1"

    def acquire(self) -> bool:
        if self._disabled:
            return True
        now = time.time()
        elapsed = now - self.last_refill
        refill = int(elapsed / self.refill_interval_ms)
        if refill > 0:
            self.tokens = min(self.max_tokens, self.tokens + refill)
            self.last_refill = now
        
        if self.tokens > 0:
            self.tokens -= 1
            return True
        return False

class LogUtils:
    """Utilities for safe logging in a daemonized process."""
    
    @staticmethod
    def log(msg: str):
        print(f"[Zygote] {msg}")

    @staticmethod
    def debug_log(msg: str):
        # Write debug log to file for daemon mode debugging.
        try:
            from .paths import VeloPaths
            log_path = VeloPaths.zygote_log()
            with open(log_path, "a") as f:
                f.write(f"[{time.ctime()}] {msg}\n")
        except:
            pass
