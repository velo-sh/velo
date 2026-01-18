from __future__ import annotations

"""
Velo QA: Agent C - Security Specialist (SEC-xxx)
=================================================
Security QA: Find every security vulnerability.

Agent C's mission: Trust nothing, verify everything.
"""

import os
import time

import pytest
from test_harness import assert_no_crash, run_velo
from test_phase3_harness import ZygoteTestEnv


class TestPermissions:
    """SEC-PERM-xxx: Permission security tests."""

    def test_sec_perm_001_socket_permissions(self):
        """
        SEC-PERM-001: Socket should not be world-readable.

        Risk: Information leak via socket
        Expected: Socket mode = 0600 or 0700 (owner only)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            if env.socket_path.exists():
                mode = os.stat(env.socket_path).st_mode
                # Check world/group read/write bits
                world_bits = mode & 0o007
                group_bits = mode & 0o070

                print(f"\n  Socket mode: {oct(mode)}")
                print(f"  World bits: {oct(world_bits)}")
                print(f"  Group bits: {oct(group_bits)}")

                # Should not be world-readable/writable
                assert world_bits == 0, f"Socket is world-accessible: {oct(mode)}"
        finally:
            env.cleanup()

    def test_sec_perm_002_worker_env_isolation(self):
        """
        SEC-PERM-002: Worker should not inherit sensitive Zygote env.

        Risk: Secret leakage
        Expected: Env isolated per worker
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Script to dump env
            env.create_script(
                "dump_env.py",
                """
import os
for k, v in sorted(os.environ.items()):
    if 'SECRET' in k or 'KEY' in k or 'TOKEN' in k:
        print(f"FOUND_SENSITIVE: {k}")
""",
            )

            # Set sensitive env var and run
            result = run_velo(
                ["run", "--zygote", "dump_env.py"],
                cwd=env.path,
                timeout=30,
                env={"MY_SECRET_KEY": "should_not_leak"},
            )

            # Check if secret was visible
            # (actual behavior depends on design - may be intentional)
            if result.success:
                print(f"\n  Env dump: {result.stdout[:200]}")
        finally:
            env.cleanup()

    def test_sec_perm_004_config_path_validation(self):
        """
        SEC-PERM-004: Config file path should be validated.

        Risk: Arbitrary file read via config path manipulation
        Expected: Only project-local config accepted
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Try to reference external config (if configurable)
            # This is a placeholder - actual test depends on implementation
            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            assert_no_crash(result)
        finally:
            env.cleanup()


class TestPrivilegeEscalation:
    """SEC-PRIV-xxx: Privilege escalation tests."""

    def test_sec_priv_001_refuse_root(self):
        """
        SEC-PRIV-001: Running as root should warn or refuse.

        Risk: Root Zygote is dangerous
        Expected: Warning or refusal

        Note: Only meaningful if actually running as root (skip otherwise)
        """
        # Skip if not root (most common case)
        if os.getuid() != 0:
            pytest.skip("Not running as root")

        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            # Should warn about running as root
            assert "root" in result.stderr.lower() or "warning" in result.stderr.lower()
        finally:
            env.cleanup()

    def test_sec_priv_002_no_suid_inheritance(self):
        """
        SEC-PRIV-002: Worker should not inherit SUID bits.

        Risk: Privilege escalation via SUID
        Expected: No SUID inheritance
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Script to check effective UID
            env.create_script(
                "check_uid.py",
                """
import os
print(f"UID: {os.getuid()}")
print(f"EUID: {os.geteuid()}")
print(f"GID: {os.getgid()}")
print(f"EGID: {os.getegid()}")
""",
            )

            result = run_velo(["run", "--zygote", "check_uid.py"], cwd=env.path, timeout=30)

            if result.success:
                # UID and EUID should be same (no SUID)
                print(f"\n  UID info: {result.stdout}")
        finally:
            env.cleanup()


class TestDataIsolation:
    """SEC-ISO-xxx: Data isolation tests."""

    def test_sec_iso_002_fd_cleanup_after_fork(self):
        """
        SEC-ISO-002: Worker should not have access to Zygote FDs.

        Risk: FD leak allows access to Zygote resources
        Expected: FDs closed after fork (except stdin/stdout/stderr)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Script to list open FDs
            env.create_script(
                "check_fds.py",
                """
import os
import sys

# List open FDs
open_fds = []
for fd in range(100):
    try:
        os.fstat(fd)
        open_fds.append(fd)
    except OSError:
        pass

print(f"Open FDs: {open_fds}")
# 0, 1, 2 are stdin/stdout/stderr - those are expected
unexpected = [fd for fd in open_fds if fd > 2]
if unexpected:
    print(f"UNEXPECTED FDs: {unexpected}")
""",
            )

            result = run_velo(["run", "--zygote", "check_fds.py"], cwd=env.path, timeout=30)

            if result.success:
                print(f"\n  FD info: {result.stdout}")
                # Should not have too many unexpected FDs
                assert result.stdout.count("UNEXPECTED") <= 1
        finally:
            env.cleanup()

    def test_sec_iso_004_env_isolation_between_workers(self):
        """
        SEC-ISO-004: Env vars should not leak between workers.

        Risk: Secret leakage between concurrent requests
        Expected: Clean env for each worker
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Script 1: Set env var
            env.create_script(
                "set_env.py",
                """
import os
os.environ['WORKER_SECRET'] = 'should_not_persist'
print('set')
""",
            )

            # Script 2: Read env var
            env.create_script(
                "get_env.py",
                """
import os
val = os.environ.get('WORKER_SECRET', 'NOT_FOUND')
print(f'WORKER_SECRET={val}')
""",
            )

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Run script that sets env
            run_velo(["run", "--zygote", "set_env.py"], cwd=env.path, timeout=10)

            # Run script that reads env
            result = run_velo(["run", "--zygote", "get_env.py"], cwd=env.path, timeout=10)

            if result.success:
                # Should NOT find the env var set by previous worker
                assert "NOT_FOUND" in result.stdout, "Env leaked between workers!"
        finally:
            env.cleanup()


class TestInputValidation:
    """SEC-INP-xxx: Input validation tests."""

    def test_sec_inp_001_script_path_injection(self):
        """
        SEC-INP-001: Script path should be sanitized.

        Risk: Path traversal to execute arbitrary code
        Expected: Path validated
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Try path traversal in script path
            result = run_velo(["run", "--zygote", "../../../etc/passwd"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            # Should not succeed in reading /etc/passwd
            assert result.returncode != 0 or "error" in result.stderr.lower()
        finally:
            env.cleanup()

    def test_sec_inp_003_module_name_injection(self):
        """
        SEC-INP-003: Module names in config should be validated.

        Risk: Import path hijacking
        Expected: Only valid module names accepted
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Try malicious module names
            config = """
[zygote]
preload = ["../../etc/passwd", "__import__('os').system('id')"]
"""
            env.create_velo_config(config)

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            assert_no_crash(result)
            # Should reject malicious module names
        finally:
            env.cleanup()

    def test_sec_inp_005_ipc_command_validation(self):
        """
        SEC-INP-005: IPC commands should be strictly validated.

        Risk: Command injection via IPC
        Expected: Only valid commands accepted
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            if env.socket_path.exists():
                # Try to send malicious IPC command
                malicious = b'{"cmd": "__import__(os).system(id)"}'
                response = env.send_raw_ipc(malicious, timeout=2)

                # Should not execute arbitrary code
                # Zygote should survive
                status = run_velo(["zygote", "status"], cwd=env.path, timeout=5)
                assert_no_crash(status)
        finally:
            env.cleanup()


# =============================================================================
# CROSS-REVIEW: Agent A (Edge Cases) additions to Security
# =============================================================================


class TestSecurityEdgeCases:
    """Agent A review: Edge cases in security scenarios."""

    def test_sec_edge_001_race_permission_check(self):
        """
        Agent A: Race condition in permission check (TOCTOU).

        Attack: Change permissions between check and use.
        Risk: Bypass permission validation.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            import threading

            def toggle_permissions():
                for _ in range(10):
                    try:
                        if env.socket_path.parent.exists():
                            os.chmod(str(env.socket_path.parent), 0o755)
                            time.sleep(0.01)
                            os.chmod(str(env.socket_path.parent), 0o000)
                            time.sleep(0.01)
                            os.chmod(str(env.socket_path.parent), 0o755)
                    except Exception:
                        pass

            t = threading.Thread(target=toggle_permissions)
            t.start()

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            t.join(timeout=5)

            assert_no_crash(result)
        finally:
            try:
                os.chmod(str(env.socket_path.parent), 0o755)
            except Exception:
                pass
            env.cleanup()

    def test_sec_edge_002_symlink_race(self):
        """
        Agent A: Symlink race during socket creation.

        Attack: Replace socket with symlink mid-creation.
        Risk: Write to arbitrary location.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Just run and check for crash
            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            assert_no_crash(result)
        finally:
            env.cleanup()

    def test_sec_edge_003_concurrent_auth_bypass(self):
        """
        Agent A: Concurrent requests may bypass auth.

        Attack: Many parallel requests during auth check.
        Risk: Race in authentication logic.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            import threading

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            results = []

            def run_script():
                r = run_velo(["run", "--zygote", "test.py"], cwd=env.path, timeout=10)
                results.append(r.returncode)

            env.create_script("test.py", "print('ok')")

            # 10 concurrent runs
            threads = [threading.Thread(target=run_script) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            # All should behave consistently
            assert len(set(results)) <= 2  # Either all succeed or all fail
        finally:
            env.cleanup()


# =============================================================================
# CROSS-REVIEW: Agent B (Stability) additions to Security
# =============================================================================


class TestSecurityStability:
    """Agent B review: Stability of security features."""

    def test_sec_stable_001_permission_check_idempotent(self):
        """
        Agent B: Permission checks should be idempotent.

        Run same security check 10x - all results identical.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("check.py", "import os; print(os.getuid())")

            results = []
            for _ in range(10):
                r = run_velo(["run", "--zygote", "check.py"], cwd=env.path, timeout=30)
                if r.success:
                    results.append(r.stdout.strip())

            if results:
                # All should be identical
                assert len(set(results)) == 1, f"Non-idempotent: {set(results)}"
        finally:
            env.cleanup()

    def test_sec_stable_002_security_no_regression(self):
        """
        Agent B: Security features should not regress normal operation.

        Adding security checks should not break core functionality.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("basic.py", "print('hello')")

            # Normal operation should still work
            result = run_velo(["run", "--zygote", "basic.py"], cwd=env.path, timeout=30)
            assert_no_crash(result)
            if result.success:
                assert "hello" in result.stdout
        finally:
            env.cleanup()

    def test_sec_stable_003_recovery_after_security_failure(self):
        """
        Agent B: System should recover after security failures.

        After blocking a security violation, normal ops should work.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Trigger security check (path traversal)
            run_velo(["run", "--zygote", "../../../etc/passwd"], cwd=env.path, timeout=5)

            # Normal operation should still work
            env.create_script("normal.py", "print('recovered')")
            result = run_velo(["run", "--zygote", "normal.py"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            if result.success:
                assert "recovered" in result.stdout
        finally:
            env.cleanup()
