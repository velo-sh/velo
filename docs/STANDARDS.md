# Velo 项目规范 (Project Standards)

统一的命名和组织规范，确保未来开发一致性。

---

## 1. 目录结构 (Directory Structure)

```
velo/
├── .github/
│   └── workflows/
│       ├── ci.yml              # 主 CI 流水线
│       └── release.yml         # 发布流水线 (future)
├── docs/
│   ├── DEFINITION_OF_DONE.md   # 质量门标准
│   ├── rfcs/                   # RFC 设计文档
│   │   ├── README.md
│   │   └── 0001-phase-1.5-env-detection.md
│   ├── qa/                     # QA 文档
│   │   ├── README.md
│   │   ├── QA_CHECKLIST_TEMPLATE.md
│   │   └── phase-1.5-test-matrix.md
│   └── testing/                # 测试指南
│       └── phase-1.5-qa-guide.md
├── scripts/
│   ├── setup-dev.sh            # 开发环境设置
│   ├── test-phase{X.Y}.sh      # Dev 验收测试
│   └── ci-qa.sh                # QA CI 测试运行器
├── src/                        # Rust 源码
├── tests/
│   ├── corpus/                 # 测试用 Python 脚本
│   └── qa/                     # QA 对抗性测试 (pytest)
│       ├── conftest.py
│       ├── test_harness.py
│       └── test_*.py
└── target/                     # Cargo 构建产物
```

---

## 2. 命名规范 (Naming Conventions)

### 2.1 文档命名

| 类型 | 格式 | 示例 |
|------|------|------|
| RFC | `NNNN-<kebab-case>.md` | `0001-phase-1.5-env-detection.md` |
| QA 测试矩阵 | `phase-{X.Y}-test-matrix.md` | `phase-1.5-test-matrix.md` |
| QA 指南 | `phase-{X.Y}-qa-guide.md` | `phase-1.5-qa-guide.md` |
| 缺陷报告 | `phase-{X.Y}-defect-report.md` | `phase-1.5-defect-report.md` |

### 2.2 脚本命名

| 类型 | 格式 | 示例 |
|------|------|------|
| Dev 验收测试 | `test-phase{X.Y}.sh` | `test-phase1.5.sh` |
| CI 运行器 | `ci-{scope}.sh` | `ci-qa.sh` |
| 设置脚本 | `setup-{purpose}.sh` | `setup-dev.sh` |

### 2.3 测试文件命名 (Python)

| 类型 | 格式 | 示例 |
|------|------|------|
| Phase 功能测试 | `test_phase{X_Y}_features.py` | `test_phase1_5_features.py` |
| 分类测试 | `test_{category}.py` | `test_chaos_cache.py` |
| 共享基础设施 | `test_harness.py` | - |

### 2.4 CI Job 命名

| 类型 | 格式 | 示例 |
|------|------|------|
| 构建测试 | `build` | Build & Test |
| 代码质量 | `{tool}` | `clippy`, `fmt` |
| QA 测试 | `qa-tests` | QA Adversarial Tests |
| 发布 | `release` | Release |

---

## 3. 测试分类 (Test Categories)

### 3.1 测试 ID 前缀

| 前缀 | 类别 | 说明 |
|------|------|------|
| `CHAOS-` | 混沌测试 | 损坏、竞态、资源耗尽 |
| `PYDET-` | Python 检测 | 假 Python、符号链接 |
| `FUZZ-` | 输入模糊 | 恶意输入、特殊字符 |
| `ENV-` | 环境污染 | 环境变量、权限 |
| `FP-` | 指纹攻击 | uv.lock 操纵 |
| `RACE-` | 并发测试 | 竞态条件 |
| `ABI-` | ABI 兼容性 | Python 版本切换 |
| `PRF-` | 性能分析 | --profile 相关 |
| `INF-` | 系统信息 | velo info 相关 |

### 3.2 测试类命名

```python
# 格式: Test{Category}{SubCategory}
class TestCacheChaosCORRUPTION:  # Cache 类别, 损坏子类
class TestPythonDetectionFAKE:   # Python 检测, 伪造子类
class TestVeloInfo:              # 功能测试
class TestProfile:               # 功能测试
```

---

## 4. 版本与 Phase 命名

| Phase | 版本 | 代号 | 描述 |
|-------|------|------|------|
| 1 | v0.1.x | Tachyon | 基础路径缓存 |
| 1.5 | v0.2.x | - | 环境检测增强 |
| 2 | v0.3.x | Supervisor | 进程隔离 |
| 3 | v0.4.x | Zygote | 进程预热 |
| 4 | v0.5.x | - | 静态分析 |

---

## 5. 提交规范 (Commit Convention)

```
<type>: <description>

[optional body]
```

| Type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `test` | 测试添加/修改 |
| `ci` | CI 配置 |
| `chore` | 杂项维护 |
| `refactor` | 重构 |

---

## 6. CI 流水线结构

```yaml
# 并行执行
┌─────────┐  ┌─────────┐  ┌─────────┐
│  build  │  │ clippy  │  │   fmt   │
└────┬────┘  └─────────┘  └─────────┘
     │
     ▼ (depends)
┌──────────┐
│ qa-tests │
└──────────┘
```

---

## 7. QA 工作流

```
1. Dev 提交 PR
2. CI 自动运行:
   - cargo test (单元测试)
   - clippy (代码质量)
   - fmt (格式检查)
   - qa-tests (对抗性测试)
3. QA 人工验证:
   - 填写 QA_CHECKLIST_TEMPLATE.md
   - 补充对抗性测试
4. Sign-off 发布
```

---

**Last Updated**: 2026-01-01
