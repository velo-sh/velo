# Velo 代码提交流程与常规问题修复 SOP

本文档总结了 RFC-0011 集成过程中的常规操作，旨在为后续开发提供标准化的参考流程，提高代码集成效率和稳定性。

---

## 1. 提交前本地预检查 (Pre-push Check) ⚡

在推送代码到远程分支之前，**必须**在本地运行检查脚本，以避免由于简单的格式或静态分析问题导致 CI 失败。

- **操作步骤**:
  ```bash
  # 运行集成检查脚本
  ./scripts/pre-push-check.sh
  ```
- **检查内容**:
  - `cargo fmt`: 自动修正 Rust 代码格式（如行尾空格、缩进）。
  - `cargo clippy`: 发现潜在的逻辑错误、未使用代码、非惯用写法（如可折叠的 `if`）。
  - Python 基础检查: 确保没有未使用的导入和明显的语法错误。

---

## 2. 依赖管理与安全升级 (Dependency & Security) 🛡️

升级依赖（如 FastAPI, uvicorn）时，需同时考虑安全性、稳定性及测试环境的完备性。

- **安全红线**: 确保 FastAPI 版本 >= 0.109.1 以修复 CVE-2024-24762 (ReDoS)。
- **SOP 规范**:
  - 在 `pyproject.toml` 中为生产依赖添加上界约束（如 `fastapi>=0.109.1,<1.0.0`）。
  - **切记**: 编辑 `dependencies` 时，不要遗漏或删除 `[project.optional-dependencies]` 中的 `dev` 组。如果该组被删除，CI 中的 `uv sync --extra dev` 将无法安装 `pytest`。

---

## 3. 代码质量与最佳实践 (Code Quality) 💎

### Python 部分
- **冗余导入**: 禁止在函数内部进行重复的本地导入（如果该模块已在文件顶部导入）。
- **标点符号**: 注释和文档字符串中严禁使用中文全角标点（`()`、`，`、`：`、`！`），必须映射为英文半角。
- **类型注解**: 遵循 PEP 484，使用显式的 `Optional[str]` 或 Python 3.10+ 的 `str | None`。
- **资源清理**: 使用 `try...finally` 确保 Socket 等系统资源在异常情况下也能被正确关闭。

### Rust 部分
- **Dead Code**: 及时删除未被构造或调用的 struct/function。
- **代码整洁**: 善用 `let-chaining` (if let ... && let ...) 减少嵌套深度。

---

## 4. 线程安全与信号处理 (Signal Safety) 🚦

在 Zygote 等多进程/多线程场景下，避免使用非线程安全的机制。

- **问题**: `signal.alarm()` 是进程全局的，在多线程环境下不安全且易干扰。
- **SOP 替代方案**: 改用 `os.waitpid(pid, os.WNOHANG)` 配合 `time.sleep(n)` 的轮询机制来实现超时等待。

---

## 5. 配置文件合规性 (Config Schema) ⚙️

针对 CodeRabbit 等第三方工具的配置，需严格遵守对应版本的 JSON/YAML Schema。

- **CodeRabbit(v2)**:
  - `knowledge_base` 应位于根目录，并使用 `opt_out: false` 而非 `enabled: true`。
  - `tools` 块应嵌套在 `reviews` 对象内部。
  - `summaries` 应替换为布尔值属性 `high_level_summary: true`。

---

## 6. 文档一致性 (Documentation) 📖

- **单源真实 (SSoT)**:
  - RFC 文档的状态应仅在文件头部定义，删除文件尾部或其他地方的重复状态声明。
  - 当功能实现后，将 RFC 状态从 `DRAFT` 更新为 `IMPLEMENTED`，并勾选验收标准。
- **治理同步**: 修改 `AGENTS.md` 导航时，使用链接引用（如 `[See Governance](#...)`）代替规则的全文复制，减少维护开销。

---

## 7. 紧急恢复机制 (Safety Net) 🛟

在执行 `git merge main` 等大型操作前，必须创建备份分支。

- **操作指令**:
  ```bash
  git branch backup/pre-merge-$(date +%Y%m%d-%H%M%S)
  ```
- **记录恢复点**: 记录当前 HEAD 的 Commit Hash，以便在合并逻辑出错或冲突解决失败时快速回滚。
