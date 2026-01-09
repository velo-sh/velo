"""
Velo Fork Implementation
"""
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
try:
    from .lifecycle import post_fork_reinit, WorkerRegistry
    from .utils import LogUtils
except (ImportError, ValueError):
    from lifecycle import post_fork_reinit, WorkerRegistry  # type: ignore[no-redef, import-not-found]
    from utils import LogUtils  # type: ignore[no-redef, import-not-found]

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
            if not stat_mod.S_ISREG(st.st_mode):
                LogUtils.log(f"Security Violation: FD {self.fd} is not a regular file")
                return False
            if self.expected_size and st.st_size < self.expected_size:
                LogUtils.log(f"Security Violation: SHM size mismatch ({st.st_size} < {self.expected_size})")
                return False
            return True
        except Exception as e:
            LogUtils.log(f"FD Validation failed: {e}")
            return False

    def close(self):
        try:
            os.close(self.fd)
        except:
            pass

    @classmethod
    def from_command(cls, cmd: Dict[str, Any]) -> Optional['InboundSharedMemory']:
        fd = cmd.get('shm_fd')
        size = cmd.get('shm_size')
        if fd is not None:
            return cls(int(fd), int(size) if size else 0)
        return None

class ForkHandler:
    """Handles the forking logic and child process environment setup."""

    @staticmethod
    def handle_fork(
        cmd: Dict[str, Any],
        worker_registry: WorkerRegistry,
        preloaded_modules: List[str]
    ) -> int:
        """Fork and execute script."""
        script_path = cmd.get("script_path")
        args = cmd.get("args", [])
        env = cmd.get("env", {})
        stdout_path = cmd.get("stdout_path")
        stderr_path = cmd.get("stderr_path")
        exit_code_path = cmd.get("exit_code_path")
        worker_ttl = cmd.get("worker_ttl", 3600)
        
        # Memory Gravity (SHM Support)
        shm = InboundSharedMemory.from_command(cmd)
        shm_fd = shm.fd if shm else None
        shm_size = shm.expected_size if shm else None

        pid = os.fork()

        if pid == 0:  # Child process
            try:
                # 1. Cord-Cutting (Security)
                # Keep stdout/stderr/shm_fd if we have them
                keep = {0, 1, 2}
                if shm_fd is not None: keep.add(shm_fd)
                
                post_fork_reinit(keep_fds=keep)
                
                # RFC-0012: Activate security shield in worker after fork
                try:
                    from .shield import ImportShield
                    ImportShield.activate()
                except (ImportError, ValueError):
                    try:
                        from shield import ImportShield  # type: ignore[no-redef, import-not-found]
                        ImportShield.activate()
                    except: pass
                
                # 2. Execution
                exit_code = ForkHandler._child_process(
                    script_path=script_path,
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
                    shm_fd=shm_fd,
                    shm_size=shm_size
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
            worker_registry.add(pid, metadata={"script": script_path})
            return pid

    @staticmethod
    def _child_process(
        script_path: str, args: List[str], env: Dict[str, str], stdout_path: Optional[str],
        stderr_path: Optional[str], exit_code_path: Optional[str],
        fast_mode: bool, bundle_path: Optional[str], project_root: Optional[str],
        max_bundle_size: Optional[int], worker_ttl: int,
        shm_fd: Optional[int] = None,
        shm_size: Optional[int] = None
    ) -> int:
        # 0. TITANIUM RULE: Recursive No Orphans (Linux Only)
        #    Ensure THIS child dies if Zygote (Parent) dies.
        #    Ported from main branch commit e10380a.
        if sys.platform.startswith("linux"):
            try:
                import ctypes
                try:
                    libc = ctypes.CDLL("libc.so.6")
                except:
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
        
        # 2.5 Security: Activate ImportShield (Trap 178.5)
        try:
            from velo_zygote.shield import ImportShield
            ImportShield.activate()
        except ImportError:
            pass
        
        # 3. Path Normalization
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
            if not script_path and not fast_mode:
                raise ValueError("Neither script_path nor fast_mode provided")
            
            if script_path:
                # Standard script execution
                sys.argv = [script_path] + args
                p = Path(script_path)
                
                # SHM Hand-off (Phase 7.3)
                if shm_fd is not None:
                    os.environ["VELO_SHM_FD"] = str(shm_fd)
                    os.environ["VELO_SHM_SIZE"] = str(shm_size)
                
                if not p.exists():
                    raise FileNotFoundError(f"Forensic Execution Failure: Script '{script_path}' vanished before execution start.")
                
                with open(script_path, "rb") as f:
                    try:
                        code = compile(f.read(), script_path, "exec")
                    except Exception as e:
                        raise RuntimeError(f"Compilation Intent Failure: Target '{script_path}' is not a valid Python script: {e}")
                    
                    # Prepare execution environment
                    child_globals = {
                        "__name__": "__main__",
                        "__file__": os.path.abspath(script_path),
                        "__builtins__": __builtins__,
                        "__doc__": None,
                        "__package__": None,
                        "__loader__": None,
                        "__spec__": None,
                    }
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
            except: pass
        
        # 6. Final Cleanup
        ForkHandler._cleanup_child(stdout_path, stderr_path, exit_code_path, exit_code)
        
        return exit_code

    @staticmethod
    def _redirect_io(stdout_path: Optional[str], stderr_path: Optional[str]):
        if stdout_path:
            try:
                sys.stdout = open(stdout_path, "a")
            except OSError as e:
                print(f"Forensic IO Warning: Failed to redirect stdout to '{stdout_path}': {e}", file=sys.stderr)
        if stderr_path:
            try:
                sys.stderr = open(stderr_path, "a")
            except OSError as e:
                print(f"Forensic IO Warning: Failed to redirect stderr to '{stderr_path}': {e}", file=sys.stderr)

    @staticmethod
    def _activate_fast_mode(bundle_path: Optional[str], project_root: Optional[str], max_size: Optional[int]) -> None:
        """Specialized loading for pre-compiled or bundled apps."""
        # Implementation details...
        pass

    @staticmethod
    def _cleanup_child(stdout_path: Optional[str], stderr_path: Optional[str], exit_code_path: Optional[str], exit_code: int) -> None:
        if exit_code_path:
            try:
                with open(exit_code_path, "w") as f:
                    f.write(str(exit_code))
            except: pass
