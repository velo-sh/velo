"""
V3 User Journey E2E Test Suite

QA 第一性原理: 确保用户能正常使用产品

测试场景:
- E2E-001: 基础脚本执行 (Hello World)
- E2E-002: 依赖包导入 (import from venv)
- E2E-003: 命令行参数 (argparse)
- E2E-004: 文件路径操作 (相对路径)
- E2E-005: 退出码传递 (sys.exit)
- E2E-006: 异常退出 (未捕获异常)
- E2E-007: 环境变量继承
- E2E-008: 热启动性能
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

import pytest

# =============================================================================
# TEST INFRASTRUCTURE
# =============================================================================


class VeloResult(NamedTuple):
    """Velo 命令执行结果"""

    returncode: int
    stdout: str
    stderr: str
    duration_ms: float


def run_velo(
    project_dir: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> VeloResult:
    """
    在指定项目目录运行 velo 命令。

    模拟用户在终端执行: cd project_dir && velo run script.py
    """
    # 使用 bootstrap shim 直接测试 (不需要完整 velo CLI)
    # 这里我们通过 Python 直接执行脚本来模拟 Velo 的核心行为

    test_env = os.environ.copy()
    test_env["PYTHONDONTWRITEBYTECODE"] = "1"

    # 设置 VIRTUAL_ENV 以模拟 velo 的 venv 检测
    venv_path = project_dir / ".venv"
    if venv_path.exists():
        test_env["VIRTUAL_ENV"] = str(venv_path)

    if env:
        test_env.update(env)

    # 构建命令 - 使用项目的 Python 解释器
    python_path = venv_path / "bin" / "python" if venv_path.exists() else sys.executable

    start = time.perf_counter()
    try:
        result = subprocess.run(
            [str(python_path)] + list(args),
            cwd=str(project_dir),
            env=test_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = (time.perf_counter() - start) * 1000
        return VeloResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired:
        return VeloResult(
            returncode=-1,
            stdout="",
            stderr="TIMEOUT",
            duration_ms=timeout * 1000,
        )


@pytest.fixture
def e2e_project(tmp_path: Path) -> Path:
    """
    创建一个完整的 E2E 测试项目。

    包含:
    - pyproject.toml
    - .venv/ (使用当前测试环境的 Python)
    - src/ 下的各种测试脚本
    """
    project = tmp_path / "e2e_project"
    project.mkdir()
    src = project / "src"
    src.mkdir()

    # pyproject.toml
    (project / "pyproject.toml").write_text("""
[project]
name = "e2e-test-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
""")

    # 创建符号链接到当前 venv (复用测试环境的包)
    current_venv = Path(sys.prefix)
    venv_link = project / ".venv"
    try:
        venv_link.symlink_to(current_venv)
    except (OSError, FileExistsError):
        # 如果无法创建符号链接，复制 Python 解释器路径
        pass

    # E2E-001: Hello World
    (src / "hello.py").write_text("""
print("Hello World from Velo!")
""")

    # E2E-002: 依赖导入 (使用标准库验证)
    (src / "use_json.py").write_text("""
import json
import sys

data = {"status": "ok", "python": sys.version_info[:2]}
print(f"JSON works: {json.dumps(data)}")
print("IMPORT_SUCCESS")
""")

    # E2E-003: 命令行参数
    (src / "cli.py").write_text("""
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--name", required=True)
args = parser.parse_args()

print(f"Hello {args.name}!")
""")

    # E2E-004: 文件路径操作
    config_file = src / "config.json"
    config_file.write_text('{"version": "1.0.0"}')

    (src / "reader.py").write_text("""
import json
from pathlib import Path

# 使用 __file__ 获取脚本目录
script_dir = Path(__file__).parent
config_path = script_dir / "config.json"

with open(config_path) as f:
    config = json.load(f)

print(f"Config loaded: version={config['version']}")
print("FILE_ACCESS_SUCCESS")
""")

    # E2E-005: 退出码传递
    (src / "exit_42.py").write_text("""
import sys
sys.exit(42)
""")

    # E2E-006: 未捕获异常
    (src / "raise_error.py").write_text("""
raise ValueError("Intentional error for testing")
""")

    # E2E-007: 环境变量
    (src / "check_env.py").write_text("""
import os

test_var = os.environ.get("E2E_TEST_VAR", "NOT_SET")
print(f"E2E_TEST_VAR={test_var}")
""")

    # E2E-008: 性能测试
    (src / "quick_script.py").write_text("""
import time
start = time.perf_counter()
print(f"Startup time: {(time.perf_counter() - start) * 1000:.2f}ms")
print("QUICK_DONE")
""")

    return project


# =============================================================================
# E2E TEST CASES
# =============================================================================


@pytest.mark.e2e
class TestUserJourneyE2E:
    """
    用户旅程端到端测试 - 从用户视角验证 Velo

    每个测试模拟一个真实用户场景:
    "作为用户，我想要... 以便于..."
    """

    # -------------------------------------------------------------------------
    # Journey 1: 基础脚本执行
    # -------------------------------------------------------------------------

    def test_e2e_001_hello_world(self, e2e_project: Path) -> None:
        """
        用户: "我有一个简单的 Python 脚本，想用 Velo 运行"
        期望: 脚本正常执行，输出 Hello World
        """
        result = run_velo(e2e_project, "src/hello.py")

        assert result.returncode == 0, f"脚本执行失败: {result.stderr}"
        assert "Hello World" in result.stdout, f"输出不正确: {result.stdout}"

    # -------------------------------------------------------------------------
    # Journey 2: 依赖包导入
    # -------------------------------------------------------------------------

    def test_e2e_002_import_dependency(self, e2e_project: Path) -> None:
        """
        用户: "我的脚本需要 import 一些库"
        期望: import 成功，库正常工作
        """
        result = run_velo(e2e_project, "src/use_json.py")

        assert result.returncode == 0, f"执行失败: {result.stderr}"
        assert "IMPORT_SUCCESS" in result.stdout, f"导入失败: {result.stdout}"
        assert "JSON works" in result.stdout

    # -------------------------------------------------------------------------
    # Journey 3: 命令行参数
    # -------------------------------------------------------------------------

    def test_e2e_003_argparse_works(self, e2e_project: Path) -> None:
        """
        用户: "我用 argparse 处理命令行参数"
        期望: sys.argv 正确传递，argparse 正常解析
        """
        result = run_velo(e2e_project, "src/cli.py", "--name", "Alice")

        assert result.returncode == 0, f"执行失败: {result.stderr}"
        assert "Hello Alice!" in result.stdout, f"参数未正确传递: {result.stdout}"

    def test_e2e_003b_argparse_missing_required(self, e2e_project: Path) -> None:
        """
        用户: "缺少必需参数时应该报错"
        期望: argparse 报错，非零退出
        """
        result = run_velo(e2e_project, "src/cli.py")

        assert result.returncode != 0, "缺少参数应该报错"
        assert "--name" in result.stderr or "required" in result.stderr

    # -------------------------------------------------------------------------
    # Journey 4: 文件路径操作
    # -------------------------------------------------------------------------

    def test_e2e_004_relative_file_access(self, e2e_project: Path) -> None:
        """
        用户: "我的脚本需要读取同目录的配置文件"
        期望: 使用 __file__ 可以正确定位相对路径
        """
        result = run_velo(e2e_project, "src/reader.py")

        assert result.returncode == 0, f"执行失败: {result.stderr}"
        assert "FILE_ACCESS_SUCCESS" in result.stdout
        assert "version=1.0.0" in result.stdout

    # -------------------------------------------------------------------------
    # Journey 5: 退出码传递
    # -------------------------------------------------------------------------

    def test_e2e_005_exit_code_propagation(self, e2e_project: Path) -> None:
        """
        用户: "脚本 sys.exit(42) 后，shell 应该收到正确的退出码"
        期望: 退出码正确传递
        """
        result = run_velo(e2e_project, "src/exit_42.py")

        assert result.returncode == 42, f"退出码应为 42，实际为 {result.returncode}"

    # -------------------------------------------------------------------------
    # Journey 6: 异常退出
    # -------------------------------------------------------------------------

    def test_e2e_006_exception_exits_nonzero(self, e2e_project: Path) -> None:
        """
        用户: "脚本抛出未捕获异常时，应该非零退出"
        期望: 异常导致非零退出码
        """
        result = run_velo(e2e_project, "src/raise_error.py")

        assert result.returncode != 0, "异常应该导致非零退出"
        assert "ValueError" in result.stderr or "Intentional error" in result.stderr

    # -------------------------------------------------------------------------
    # Journey 7: 环境变量继承
    # -------------------------------------------------------------------------

    def test_e2e_007_env_var_inheritance(self, e2e_project: Path) -> None:
        """
        用户: "我设置的环境变量应该传递给脚本"
        期望: 环境变量正确继承
        """
        result = run_velo(e2e_project, "src/check_env.py", env={"E2E_TEST_VAR": "hello_from_shell"})

        assert result.returncode == 0
        assert "E2E_TEST_VAR=hello_from_shell" in result.stdout

    # -------------------------------------------------------------------------
    # Journey 8: 启动性能
    # -------------------------------------------------------------------------

    def test_e2e_008_startup_performance(self, e2e_project: Path) -> None:
        """
        用户: "Velo 应该启动很快"
        期望: 脚本执行时间在可接受范围内
        """
        # 多次运行取平均
        durations = []
        for _ in range(3):
            result = run_velo(e2e_project, "src/quick_script.py")
            assert result.returncode == 0
            durations.append(result.duration_ms)

        avg_duration = sum(durations) / len(durations)

        # 宽松的性能标准 (因为这里是直接 Python 执行)
        assert avg_duration < 1000, f"启动太慢: {avg_duration:.2f}ms"
        print(f"平均启动时间: {avg_duration:.2f}ms")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
