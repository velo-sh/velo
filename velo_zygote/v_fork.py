"""
Velo Fork Implementation
"""

import os
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional

try:
    from .utils import LogUtils
    from .worker_lifecycle import WorkerRegistry, post_fork_reinit
except (ImportError, ValueError):
    from utils import LogUtils  # type: ignore[no-redef, import-not-found]
    from worker_lifecycle import WorkerRegistry, post_fork_reinit  # type: ignore[no-redef, import-not-found]


class InboundSharedMemory:
    """Encapsulates validation and handling of inbound shared memory FDs."""

    def __init__(self, fd: int, expected_size: int):
        self.fd = fd
        self.expected_size = expected_size

    def validate(self) -> bool:
        """Validate the FD is a regular file with correct size."""
        try:
            import stat as stat_mod

            st = os.fstat(self.fd)
            # macOS shm_open fds often return mode 0 (not S_IFREG)
            if not stat_mod.S_ISREG(st.st_mode) and not (sys.platform == "darwin" and st.st_mode == 0):
                LogUtils.log(f"Security Violation: FD {self.fd} is not a regular file (mode: {oct(st.st_mode)})")
                return False
            if self.expected_size and st.st_size < self.expected_size:
                LogUtils.log(f"Security Violation: SHM size mismatch ({st.st_size} < {self.expected_size})")
                return False
            return True
        except Exception as e:
            LogUtils.log(f"FD Validation failed: {e}")
            return False

    def close(self) -> None:
        try:
            os.close(self.fd)
        except Exception:
            pass

    @classmethod
    def from_command(cls, cmd: dict[str, Any]) -> Optional["InboundSharedMemory"]:
        fd = cmd.get("shm_fd")
        size = cmd.get("shm_size")
        if fd is not None:
            return cls(int(fd), int(size) if size else 0)
        return None


class ForkHandler:
    """Handles the forking logic and child process environment setup."""

    @staticmethod
    def handle_gateway_fork(
        sock: Any,
        worker_registry: WorkerRegistry,
        nodeid: str = "worker",
        env: dict[str, str] | None = None,
        project_root: str | None = None,
    ) -> int:
        """
        Phase 14 P1: Fork a gateway worker that takes over the socket.
        """
        pid = os.fork()
        if pid == 0:
            # CHILD: Take over socket
            try:
                # 1. Cord-Cutting
                sock_fd = sock.fileno()
                # Ensure the socket is in blocking mode for execnet
                sock.setblocking(True)

                post_fork_reinit(keep_fds={0, 1, 2, sock_fd})

                # RFC-0029: Mark this as a miracle worker to bypass redundant forks
                os.environ["VELO_MIRACLE_WORKER"] = "1"
                os.environ["VELO_IS_ZYGOTE"] = "1"

                # Apply env from pytest master (PYTHONPATH propagation)
                if env:
                    for key, value in env.items():
                        if value:  # Only set non-empty values
                            os.environ[key] = value

                # RFC-0028: Project Root Alignment
                if project_root and os.path.isdir(project_root):
                    os.chdir(project_root)
                    LogUtils.debug_log(f"Miracle Worker chdir to project_root: {project_root}")
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)

                # 2. Run execnet bootstrap
                ForkHandler._run_execnet_gateway(sock, nodeid=nodeid)
                os._exit(0)
            except Exception as e:
                try:
                    LogUtils.log(f"Gateway Worker Error: {e}")
                    traceback.print_exc()
                except Exception:
                    pass
                os._exit(1)
        else:
            # PARENT: Register worker
            worker_registry.add(pid)
            return pid

    @staticmethod
    def _wait_for_ready(socket_path: str, timeout: float = 5.0) -> bool:
        """
        Wait for a UDS socket to become available and responding.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                # Try to connect to the socket
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                # handle abstract sockets
                path = socket_path
                if path.startswith("@"):
                    path = "\0" + path[1:]
                sock.connect(path)
                sock.close()
                return True
            except (TimeoutError, ConnectionRefusedError, FileNotFoundError, OSError):
                time.sleep(0.1)
        return False

    @staticmethod
    def _run_execnet_gateway(sock: Any, nodeid: str = "worker") -> None:
        """
        Bootstraps the execnet worker logic on the provided socket.
        """
        import execnet.gateway_base
        from execnet.gateway_socket import SocketIO

        # RFC-0029: The Zygote worker becomes the execnet gateway directly.
        # This eliminates the need for an intermediate 'python' process.
        io = SocketIO(sock, execmodel=execnet.gateway_base.get_execmodel("thread"))
        execnet.gateway_base.serve(io, nodeid)

    @staticmethod
    def handle_idle_fork(
        worker_registry: WorkerRegistry,
        preloaded_modules: list[str],
        warmed_server: Any = None,
        warmed_config: Any = None,
    ) -> tuple[int, int]:
        """
        P0: Pre-fork an idle worker.
        Returns (pid, control_pipe_write_fd).
        """
        import json

        # 0. Setup Control Pipe
        r, w = os.pipe()

        pid = os.fork()
        if pid == 0:  # Child (Idle Worker)
            os.close(w)
            try:
                # 1. Cord-Cutting
                post_fork_reinit(keep_fds={0, 1, 2, r})

                # 2. Block until task arrives
                LogUtils.log(f"Idle Worker {os.getpid()} waiting for task...")
                task_data = os.read(r, 65536)
                if not task_data:
                    os._exit(0)

                cmd = json.loads(task_data.decode())
                os.close(r)

                # 3. Standard Child Execution
                exit_code = ForkHandler._child_process(
                    script_path=cmd.get("script_path", ""),
                    module_name=cmd.get("module"),
                    args=cmd.get("args", []),
                    env=cmd.get("env", {}),
                    stdout_path=cmd.get("stdout_path"),
                    stderr_path=cmd.get("stderr_path"),
                    exit_code_path=cmd.get("exit_code_path"),
                    fast_mode=cmd.get("fast_mode", False),
                    bundle_path=cmd.get("bundle_path"),
                    project_root=cmd.get("project_root"),
                    max_bundle_size=cmd.get("max_bundle_size"),
                    worker_ttl=cmd.get("worker_ttl", 3600),
                    shm_fd=cmd.get("shm_fd"),
                    shm_size=cmd.get("shm_size"),
                    warmed_server=warmed_server,
                    warmed_config=warmed_config,
                )
                os._exit(exit_code)
            except Exception as e:
                LogUtils.log(f"Idle Worker Error: {e}")
                os._exit(1)

        else:  # Parent (Zygote)
            os.close(r)
            worker_registry.add(pid, metadata={"type": "idle"})
            return pid, w

    @staticmethod
    def handle_fork(
        cmd: dict[str, Any],
        worker_registry: WorkerRegistry,
        preloaded_modules: list[str],
        warmed_server: Any = None,
        warmed_config: Any = None,
    ) -> int:
        """Fork and execute script."""
        # Memory Gravity (SHM Support)
        shm = InboundSharedMemory.from_command(cmd)
        shm_fd = shm.fd if shm else None

        script_path = cmd.get("script_path")
        module_name = cmd.get("module")
        args = cmd.get("args", [])
        env = cmd.get("env", {})
        stdout_path = cmd.get("stdout_path")
        stderr_path = cmd.get("stderr_path")
        exit_code_path = cmd.get("exit_code_path")
        worker_ttl = cmd.get("worker_ttl", 3600)

        LogUtils.log(f"Forking child process for {module_name or script_path}...")
        pid = os.fork()

        if pid == 0:  # Child process
            try:
                # 1. Cord-Cutting (Security)
                # Keep stdout/stderr/shm_fd if we have them
                keep = {0, 1, 2}
                if shm_fd is not None:
                    keep.add(shm_fd)

                post_fork_reinit(keep_fds=keep)

                # RFC-0012: Activate security shield in worker after fork
                try:
                    from .v_shield import ImportShield

                    ImportShield.activate()
                except (ImportError, ValueError):
                    try:
                        from v_shield import ImportShield  # type: ignore[no-redef, import-not-found]

                        ImportShield.activate()
                    except Exception:
                        pass

                # RFC-0012: Hygiene - Restore SIGPIPE to default for worker
                import signal

                signal.signal(signal.SIGPIPE, signal.SIG_DFL)

                # 2. Execution
                exit_code = ForkHandler._child_process(
                    script_path=str(script_path) if script_path else "",
                    module_name=module_name,
                    args=args,
                    env=env,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    exit_code_path=exit_code_path,
                    fast_mode=cmd.get("fast_mode", False),
                    bundle_path=cmd.get("bundle_path"),
                    project_root=cmd.get("project_root"),
                    max_bundle_size=cmd.get("max_bundle_size"),
                    worker_ttl=worker_ttl,
                    shm_fd=shm.fd if shm else None,
                    shm_size=shm.expected_size if shm else None,
                    warmed_server=warmed_server,
                    warmed_config=warmed_config,
                )
                os._exit(exit_code)
            except Exception as e:
                with open(stderr_path or "/dev/stderr", "a") as f:
                    f.write(f"FATAL CHILD ERROR: {e}\n")
                    traceback.print_exc(file=f)
                os._exit(1)

        else:  # Parent process
            if shm:
                shm.close()

            # STB-SYNC-FORK: Wait for worker to be ready before returning
            # This ensures the supervisor doesn't run health checks on a ghost socket
            uds_path = None
            for i, arg in enumerate(args):
                if arg == "--uds" and i + 1 < len(args):
                    uds_path = args[i + 1]
                    break

            if uds_path:
                LogUtils.log(f"Waiting for worker {pid} to bind to {uds_path}...")
                # Increase internal wait timeout scaled by VELO_TIMEOUT_MULTIPLIER (RFC-0012)
                multiplier = float(os.environ.get("VELO_TIMEOUT_MULTIPLIER", "1.0"))
                timeout = 10.0 * multiplier
                if not ForkHandler._wait_for_ready(uds_path, timeout=timeout):
                    LogUtils.log(f"Warning: Worker {pid} socket {uds_path} not ready after {timeout}s")
                else:
                    LogUtils.log(f"Worker {pid} is READY on {uds_path}")

            worker_registry.add(pid, metadata={"script": script_path})
            return pid

    @staticmethod
    def _child_process(
        script_path: str,
        module_name: str | None,
        args: list[str],
        env: dict[str, str],
        stdout_path: str | None,
        stderr_path: str | None,
        exit_code_path: str | None,
        fast_mode: bool,
        bundle_path: str | None,
        project_root: str | None,
        max_bundle_size: int | None,
        worker_ttl: int,
        shm_fd: int | None = None,
        shm_size: int | None = None,
        warmed_server: Any = None,
        warmed_config: Any = None,
    ) -> int:
        # RFC-0030: Mark as Zygote-accelerated for process diagnostics
        os.environ["VELO_IS_ZYGOTE"] = "1"

        # 0. TITANIUM RULE: Recursive No Orphans (Linux Only)
        #    Ensure THIS child dies if Zygote (Parent) dies.
        #    Ported from main branch commit e10380a.
        if sys.platform.startswith("linux"):
            try:
                import ctypes

                try:
                    libc = ctypes.CDLL("libc.so.6")
                except Exception:
                    libc = ctypes.CDLL(None)

                PR_SET_PDEATHSIG = 1
                SIGKILL = 9
                res = libc.prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0)
                if res != 0:
                    LogUtils.log(f"PDEATHSIG Failed (code {res})")
                else:
                    LogUtils.log("PDEATHSIG Set")
            except Exception as e:
                LogUtils.log(f"PDEATHSIG Exception: {e}")

        # 1. IO Redirection
        ForkHandler._redirect_io(stdout_path, stderr_path)

        # 2. Environment Setup
        os.environ.update(env)

        # DEF-VTEST-GUARD: Mark as Zygote worker to prevent pytest-velo plugin re-initialization
        os.environ["VELO_IS_ZYGOTE"] = "1"

        # 2.5 Security: Activate ImportShield (Trap 178.5)
        try:
            from velo_zygote.v_shield import ImportShield

            ImportShield.activate()
        except ImportError:
            pass

        # TITANIUM RULE: No Orphans (macOS)
        # Activate kqueue monitor in worker
        # TITANIUM RULE: No Orphans (macOS)
        # Activate kqueue monitor in worker
        # TITANIUM RULE: No Orphans (macOS)
        # Activate monitor in worker to prevent zombies if Zygote dies
        if sys.platform == "darwin":
            from velo_zygote.utils import MacOSDeathSigMonitor

            MacOSDeathSigMonitor.start_monitoring()

        # 3. Project Root Alignment (CRITICAL: Must happen BEFORE imports)
        # This is THE fix for "file or directory not found" errors
        if project_root and os.path.isdir(project_root):
            os.chdir(project_root)
            LogUtils.debug_log(f"Worker chdir to project_root: {project_root}")
            # Also add to PYTHONPATH for imports
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

        # 3b. Path Normalization (script dir)
        if script_path:
            script_dir = os.path.dirname(os.path.abspath(script_path))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

        # 4. Fast Mode Activation
        if fast_mode:
            ForkHandler._activate_fast_mode(bundle_path, project_root, max_bundle_size)

        # 5. Execution
        exit_code = 0
        try:
            if not script_path and not fast_mode and not module_name:
                raise ValueError("Neither script_path, module_name nor fast_mode provided")

            if module_name:
                # Module execution via runpy (Phase 9.x Alignment)
                import runpy

                sys.argv = [module_name] + args

                # Injection of Zygote environment
                child_globals = {
                    "__VELO_WARM_SERVER__": warmed_server,
                    "__VELO_WARM_CONFIG__": warmed_config,
                }

                # SHM Hand-off (Phase 7.3)
                if shm_fd is not None:
                    os.environ["VELO_SHM_FD"] = str(shm_fd)
                    os.environ["VELO_SHM_SIZE"] = str(shm_size)
                    try:
                        from velo_zygote.memory import MEMORY_MANAGER

                        shm_obj = MEMORY_MANAGER.attach(shm_fd, shm_size if shm_size else 0)
                        if shm_obj is not None:
                            child_globals["VELO_SHM"] = shm_obj
                    except Exception:
                        pass

                runpy.run_module(module_name, init_globals=child_globals, run_name="__main__", alter_sys=True)

            elif script_path:
                # Standard script execution
                sys.argv = [script_path] + args
                p = Path(script_path)

                # SHM Hand-off (Phase 7.3)
                if shm_fd is not None:
                    os.environ["VELO_SHM_FD"] = str(shm_fd)
                    os.environ["VELO_SHM_SIZE"] = str(shm_size)

                if not p.exists():
                    raise FileNotFoundError(
                        f"Forensic Execution Failure: Script '{script_path}' vanished before execution start."
                    )

                with open(script_path, "rb") as f:
                    try:
                        code = compile(f.read(), script_path, "exec")
                    except Exception as e:
                        raise RuntimeError(
                            f"Compilation Intent Failure: Target '{script_path}' is not a valid Python script: {e}"
                        ) from e

                    # Prepare execution environment
                    child_globals = {
                        "__name__": "__main__",
                        "__file__": os.path.abspath(script_path),
                        "__builtins__": __builtins__,
                        "__VELO_WARM_SERVER__": warmed_server,
                        "__VELO_WARM_CONFIG__": warmed_config,
                        "__doc__": None,
                        "__package__": None,
                        "__loader__": None,
                        "__spec__": None,
                    }

                    # Inject VELO_SHM if available
                    if shm_fd is not None:
                        try:
                            # Try absolute import first (standard in Velo)
                            from velo_zygote.memory import MEMORY_MANAGER
                        except ImportError:
                            try:
                                # Try relative import
                                from .memory import MEMORY_MANAGER
                            except (ImportError, ValueError):
                                # Fallback for standalone execution
                                try:
                                    from memory import MEMORY_MANAGER  # type: ignore[no-redef]
                                except ImportError:
                                    MEMORY_MANAGER = None  # type: ignore[assignment]

                        if MEMORY_MANAGER:
                            try:
                                shm_obj = MEMORY_MANAGER.attach(shm_fd, shm_size if shm_size else 0)
                                if shm_obj is not None:
                                    child_globals["VELO_SHM"] = shm_obj
                            except Exception as e:
                                sys.stderr.write(f"SHM Attachment Warning: {e}\n")

                    if os.environ.get("VELO_DEBUG_FORK") == "1":
                        LogUtils.log(f"Child {os.getpid()} executing {script_path}")
                    exec(code, child_globals)
            elif fast_mode:
                # Already handled in _activate_fast_mode
                pass

        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 0
        except Exception as e:
            sys.stderr.write(f"Worker Exception: {e}\n")
            traceback.print_exc(file=sys.stderr)
            exit_code = 1
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass

        # 6. Final Cleanup
        ForkHandler._cleanup_child(stdout_path, stderr_path, exit_code_path, exit_code)

        return exit_code

    @staticmethod
    def _redirect_io(stdout_path: str | None, stderr_path: str | None) -> None:
        if stdout_path:
            try:
                sys.stdout = open(stdout_path, "a")
            except OSError as e:
                print(
                    f"Forensic IO Warning: Failed to redirect stdout to '{stdout_path}': {e}",
                    file=sys.stderr,
                )
        if stderr_path:
            try:
                sys.stderr = open(stderr_path, "a")
            except OSError as e:
                print(
                    f"Forensic IO Warning: Failed to redirect stderr to '{stderr_path}': {e}",
                    file=sys.stderr,
                )

    @staticmethod
    def _activate_fast_mode(bundle_path: str | None, project_root: str | None, max_size: int | None) -> None:
        """Specialized loading for pre-compiled or bundled apps."""
        # Implementation details...
        pass

    @staticmethod
    def _cleanup_child(
        stdout_path: str | None,
        stderr_path: str | None,
        exit_code_path: str | None,
        exit_code: int,
    ) -> None:
        if exit_code_path:
            try:
                with open(exit_code_path, "w") as f:
                    f.write(str(exit_code))
            except Exception:
                pass
