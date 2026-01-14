"""
Velo Utilities
"""
import os
import time
import contextvars
from typing import Optional

# Global context for Correlation IDs (Phase 2)
request_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_context", default=None
)
# Use EnvProfile as SSOT for environment detection
try:
    from .env_profile import ENV_PROFILE
except (ImportError, ValueError):
    from env_profile import ENV_PROFILE


class ForkRateLimiter:
    """RFC-0011 WB-005: Token bucket rate limiter for Fork DoS protection."""

    def __init__(self, max_tokens: int = 100, refill_interval_ms: int = 50):
        self.max_tokens = max_tokens
        self.refill_interval_ms = refill_interval_ms / 1000.0  # Convert to seconds
        self.tokens = max_tokens
        self.last_refill = time.time()
        # Use EnvProfile as SSOT (Phase 11.4)
        self._disabled = ENV_PROFILE.rate_limit_disabled

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
        import sys

        req_id = request_context.get()
        prefix = f"[Req:{req_id}] " if req_id else ""
        sys.stderr.write(f"[Zygote] {prefix}{msg}\n")
        sys.stderr.flush()

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
            pass


# Flight Recorder - REMOVED
# def flight_log(msg): ...


class MacOSDeathSigMonitor:
    """RFC-0012: macOS alternative to PR_SET_PDEATHSIG using kqueue/kevent (Polling Fallback)."""

    @staticmethod
    def start_monitoring():
        import sys

        if not sys.platform == "darwin":
            return

        import threading
        import os
        import time

        def monitor():
            try:
                original_ppid = os.getppid()
                if original_ppid <= 1:
                    LogUtils.log(f"Monitor: Already orphaned (Parent {original_ppid})")
                    return

                LogUtils.log(
                    f"Monitor started for Parent {original_ppid} (Polling Mode)"
                )

                while True:
                    time.sleep(0.5)  # Poll every 500ms
                    try:
                        current_ppid = os.getppid()
                        if current_ppid != original_ppid:
                            LogUtils.log(
                                f"Parent changed from {original_ppid} to {current_ppid}. Exiting."
                            )
                            break

                        # Double check if process exists (paranoid)
                        try:
                            # signal 0 check
                            os.kill(original_ppid, 0)
                        except OSError:
                            LogUtils.log(f"Parent {original_ppid} is dead. Exiting.")
                            break
                    except Exception as e:
                        pass

                # Force kill self via SIGKILL (Zero Mercy for Orphans)
                LogUtils.log("Monitor triggering suicide (SIGKILL to self)")
                import signal
                os.kill(os.getpid(), signal.SIGKILL)
            except Exception as e:
                LogUtils.log(f"Monitor failed: {e}")
                import traceback

                traceback.print_exc()

        t = threading.Thread(target=monitor, daemon=True, name="ParentMonitor")
        LogUtils.log(f"Starting ParentMonitor thread for parent {os.getppid()}")
        t.start()
