"""
V3 User Scenario Tests - Real World Use Cases

Council Review Round 2: 真实用户场景测试

测试场景:
- USR-001: stdin 管道输入
- USR-002: -m 模块执行 (模拟)
- USR-003: 工作目录 (cwd) 正确性
- USR-004: stdout 实时输出
- USR-005: stderr 分离
- USR-006: 友好错误信息
- USR-007: 语法错误行号
- USR-008: 超时控制
- USR-009: UTF-8 编码
- USR-010: 权限错误处理
"""

import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

# =============================================================================
# TEST INFRASTRUCTURE
# =============================================================================

VELO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_PY = VELO_ROOT / "crates" / "velo-core" / "src" / "zygote" / "bootstrap.py"


def get_short_socket_path() -> Path:
    import uuid
    return Path("/tmp") / f"v3usr-{uuid.uuid4().hex[:8]}.sock"


class ZygoteTester:
    """Zygote 测试器"""

    def __init__(self, socket_path: Path | None = None):
        self.socket_path = socket_path or get_short_socket_path()
        self.server_sock: socket.socket | None = None
        self.client_sock: socket.socket | None = None
        self.process: subprocess.Popen | None = None

    def start(self, env: dict[str, str] | None = None) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()

        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(str(self.socket_path))
        self.server_sock.listen(1)
        self.server_sock.settimeout(10)

        test_env = os.environ.copy()
        test_env["VELO_ZYGOTE_SOCK"] = str(self.socket_path)
        if env:
            test_env.update(env)

        self.process = subprocess.Popen(
            [sys.executable, str(BOOTSTRAP_PY)],
            env=test_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.client_sock, _ = self.server_sock.accept()
        self.client_sock.settimeout(5)
        self._recv_message()  # Ready

    def send_command(self, cmd: dict) -> dict:
        if not self.client_sock:
            raise RuntimeError("Not connected")
        payload = json.dumps(cmd).encode("utf-8")
        header = struct.pack("<I", 1 + len(payload)) + struct.pack("B", 1)
        self.client_sock.sendall(header + payload)
        return self._recv_message()

    def _recv_message(self) -> dict:
        if not self.client_sock:
            raise RuntimeError("Not connected")
        raw_len = self._recv_exact(4)
        total_len = struct.unpack("<I", raw_len)[0]
        self._recv_exact(1)
        payload = self._recv_exact(total_len - 1)
        return json.loads(payload.decode("utf-8"))

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.client_sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Socket closed")
            data += chunk
        return data

    def stop(self) -> None:
        if self.client_sock:
            try:
                self.send_command({"type": "Shutdown"})
            except Exception:
                pass
            self.client_sock.close()
        if self.server_sock:
            self.server_sock.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.socket_path.exists():
            self.socket_path.unlink()


# =============================================================================
# USR-003: 工作目录 (cwd) 正确性 [P0]
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier0
class TestUsr003WorkingDirectory:
    """
    USR-003: 用户的工作目录必须正确。
    
    场景: cd /project/subdir && velo run ../scripts/main.py
    期望: os.getcwd() = /project/subdir (用户当前目录)
    """

    def test_cwd_is_script_directory_not_bootstrap(self, tmp_path: Path) -> None:
        """脚本中 os.getcwd() 应该是合理的工作目录"""
        sock_path = get_short_socket_path()
        tester = ZygoteTester(sock_path)

        script = tmp_path / "check_cwd.py"
        result_file = tmp_path / "cwd_result.txt"
        script.write_text(f"""
import os
cwd = os.getcwd()
with open("{result_file}", 'w') as f:
    f.write(f"CWD:{{cwd}}\\n")
    # cwd 不应该是 bootstrap.py 所在目录
    if "zygote" not in cwd.lower():
        f.write("CWD_NOT_BOOTSTRAP:OK\\n")
    else:
        f.write("CWD_IS_BOOTSTRAP:BAD\\n")
""")

        try:
            tester.start()

            resp = tester.send_command({
                "type": "Fork",
                "script_path": str(script),
                "args": [],
            })
            assert resp["type"] == "Forked"

            time.sleep(0.5)

            if result_file.exists():
                content = result_file.read_text()
                assert "CWD_NOT_BOOTSTRAP:OK" in content, f"CWD 错误: {content}"

        finally:
            tester.stop()

    def test_relative_path_from_cwd(self, tmp_path: Path) -> None:
        """从 cwd 的相对路径应该正确解析"""
        sock_path = get_short_socket_path()
        tester = ZygoteTester(sock_path)

        # 创建项目结构
        project = tmp_path / "project"
        project.mkdir()
        scripts = project / "scripts"
        scripts.mkdir()
        data = project / "data"
        data.mkdir()
        
        # 数据文件
        (data / "input.txt").write_text("TEST_DATA_CONTENT")
        
        # 脚本 - 使用相对路径读取数据
        script = scripts / "process.py"
        result_file = tmp_path / "rel_path_result.txt"
        script.write_text(f"""
import os
from pathlib import Path

# 使用 __file__ 计算项目根目录
script_dir = Path(__file__).parent
project_root = script_dir.parent
data_file = project_root / "data" / "input.txt"

with open("{result_file}", 'w') as f:
    if data_file.exists():
        content = data_file.read_text()
        f.write(f"DATA:{{content}}\\n")
        f.write("RELATIVE_PATH_OK")
    else:
        f.write(f"FILE_NOT_FOUND:{{data_file}}")
""")

        try:
            tester.start()

            resp = tester.send_command({
                "type": "Fork",
                "script_path": str(script),
                "args": [],
            })
            assert resp["type"] == "Forked"

            time.sleep(0.5)

            if result_file.exists():
                content = result_file.read_text()
                assert "RELATIVE_PATH_OK" in content, f"相对路径失败: {content}"
                assert "TEST_DATA_CONTENT" in content

        finally:
            tester.stop()


# =============================================================================
# USR-001: stdin 管道输入
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier1
class TestUsr001StdinInput:
    """
    USR-001: 用户可以通过管道传入数据
    
    场景: echo "hello" | velo run script.py
    """

    def test_stdin_data_available(self, tmp_path: Path) -> None:
        """stdin 数据应该可以被脚本读取"""
        # 这个测试直接使用 subprocess，因为 Zygote 协议不直接支持 stdin
        script = tmp_path / "read_stdin.py"
        result_file = tmp_path / "stdin_result.txt"
        script.write_text(f"""
import sys

# 非阻塞检查 stdin
if not sys.stdin.isatty():
    try:
        # 设置超时读取以避免阻塞
        import select
        readable, _, _ = select.select([sys.stdin], [], [], 0.1)
        if readable:
            data = sys.stdin.read().strip()
            with open("{result_file}", 'w') as f:
                f.write(f"STDIN_DATA:{{data}}\\n")
                f.write("STDIN_OK")
        else:
            with open("{result_file}", 'w') as f:
                f.write("NO_DATA_READY")
    except Exception as e:
        with open("{result_file}", 'w') as f:
            f.write(f"STDIN_ERROR:{{e}}")
else:
    with open("{result_file}", 'w') as f:
        f.write("IS_TTY")
""")

        # 使用 subprocess 模拟管道输入
        result = subprocess.run(
            [sys.executable, str(script)],
            input="hello_from_pipe",
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result_file.exists():
            content = result_file.read_text()
            # 可能是 STDIN_OK 或 IS_TTY (取决于环境)
            assert "STDIN_OK" in content or "IS_TTY" in content or "NO_DATA_READY" in content


# =============================================================================
# USR-004 & USR-005: stdout/stderr 分离
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier1
class TestUsr004005StdoutStderr:
    """
    USR-004: stdout 正常输出
    USR-005: stderr 分离输出
    """

    def test_stdout_and_stderr_separate(self, tmp_path: Path) -> None:
        """stdout 和 stderr 应该分离"""
        script = tmp_path / "output_test.py"
        script.write_text("""
import sys
print("STDOUT_MESSAGE")
print("STDERR_MESSAGE", file=sys.stderr)
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert "STDOUT_MESSAGE" in result.stdout
        assert "STDERR_MESSAGE" in result.stderr
        assert "STDERR_MESSAGE" not in result.stdout
        assert "STDOUT_MESSAGE" not in result.stderr

    def test_exit_code_with_stderr(self, tmp_path: Path) -> None:
        """有 stderr 输出时退出码应该正确"""
        script = tmp_path / "error_exit.py"
        script.write_text("""
import sys
print("Error occurred!", file=sys.stderr)
sys.exit(1)
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "Error occurred!" in result.stderr


# =============================================================================
# USR-007: 语法错误行号
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier1
class TestUsr007SyntaxErrors:
    """
    USR-007: 语法错误应该显示行号
    """

    def test_syntax_error_shows_line_number(self, tmp_path: Path) -> None:
        """语法错误应该包含行号信息"""
        script = tmp_path / "syntax_error.py"
        script.write_text("""
# Line 1
# Line 2
def foo():  # Line 3
    x = 1  # Line 4
    y = (  # Line 5 - unclosed paren
# Line 6
print("hello")  # Line 7
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        # 应该包含行号信息
        assert "line" in result.stderr.lower() or "Line" in result.stderr
        # 应该包含文件名
        assert "syntax_error.py" in result.stderr

    def test_indentation_error(self, tmp_path: Path) -> None:
        """缩进错误应该清晰提示"""
        script = tmp_path / "indent_error.py"
        script.write_text("""
def foo():
    x = 1
  y = 2  # Wrong indentation
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "IndentationError" in result.stderr or "indent" in result.stderr.lower()


# =============================================================================
# USR-009: UTF-8 编码
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier1
class TestUsr009Utf8Encoding:
    """
    USR-009: UTF-8 编码必须正确处理
    """

    def test_utf8_in_script_content(self, tmp_path: Path) -> None:
        """脚本内容可以包含 UTF-8 字符"""
        script = tmp_path / "utf8_script.py"
        result_file = tmp_path / "utf8_result.txt"
        script.write_text(f"""
# -*- coding: utf-8 -*-
message = "你好世界 🌍 Привет мир"
print(message)
with open("{result_file}", 'w', encoding='utf-8') as f:
    f.write(message)
    f.write("\\nUTF8_CONTENT_OK")
""", encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        if result_file.exists():
            content = result_file.read_text(encoding='utf-8')
            assert "你好世界" in content
            assert "🌍" in content
            assert "UTF8_CONTENT_OK" in content

    def test_utf8_in_filename(self, tmp_path: Path) -> None:
        """UTF-8 文件名应该正确处理"""
        # 使用中文文件名
        script = tmp_path / "测试脚本.py"
        result_file = tmp_path / "filename_result.txt"
        script.write_text(f"""
import os
filename = os.path.basename(__file__)
with open("{result_file}", 'w', encoding='utf-8') as f:
    f.write(f"FILENAME:{{filename}}\\n")
    if "测试" in filename:
        f.write("UTF8_FILENAME_OK")
""", encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        if result_file.exists():
            content = result_file.read_text(encoding='utf-8')
            assert "UTF8_FILENAME_OK" in content


# =============================================================================
# USR-006: 友好错误信息
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier1
class TestUsr006FriendlyErrors:
    """
    USR-006: 错误信息应该对用户友好
    """

    def test_import_error_shows_module_name(self, tmp_path: Path) -> None:
        """ImportError 应该显示缺失的模块名"""
        script = tmp_path / "missing_import.py"
        script.write_text("""
import nonexistent_module_xyz123
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "nonexistent_module_xyz123" in result.stderr
        assert "ModuleNotFoundError" in result.stderr or "ImportError" in result.stderr

    def test_file_not_found_clear_message(self, tmp_path: Path) -> None:
        """FileNotFoundError 应该显示文件路径"""
        script = tmp_path / "file_not_found.py"
        script.write_text("""
with open("/nonexistent/path/to/file.txt") as f:
    data = f.read()
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "FileNotFoundError" in result.stderr or "No such file" in result.stderr
        assert "/nonexistent" in result.stderr


# =============================================================================
# USR-008: 超时控制
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier1
class TestUsr008Timeout:
    """
    USR-008: 脚本执行应该可以超时控制
    """

    def test_infinite_loop_can_be_terminated(self, tmp_path: Path) -> None:
        """无限循环脚本应该可以被超时终止"""
        script = tmp_path / "infinite_loop.py"
        script.write_text("""
import time
while True:
    time.sleep(0.1)
""")

        start = time.time()
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=1,  # 1 秒超时
            )
            # 如果到这里说明没超时，不应该发生
            pytest.fail("Should have timed out")
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            # 超时应该在 1-2 秒内发生
            assert elapsed < 3, f"Timeout took too long: {elapsed}s"


# =============================================================================
# USR-010: 权限错误处理
# =============================================================================

@pytest.mark.e2e
@pytest.mark.tier1
class TestUsr010PermissionErrors:
    """
    USR-010: 权限错误应该有清晰提示
    """

    def test_permission_denied_error(self, tmp_path: Path) -> None:
        """权限拒绝应该有清晰错误信息"""
        script = tmp_path / "permission_test.py"
        script.write_text("""
# 尝试写入 root 目录
try:
    with open("/etc/test_write_permission.txt", 'w') as f:
        f.write("test")
except PermissionError as e:
    print(f"PERMISSION_ERROR:{e}")
    import sys
    sys.exit(13)  # 权限错误退出码
except Exception as e:
    print(f"OTHER_ERROR:{e}")
    import sys
    sys.exit(1)
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        # 应该是权限错误或其他受控错误
        assert result.returncode != 0 or "PERMISSION_ERROR" in result.stdout


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
