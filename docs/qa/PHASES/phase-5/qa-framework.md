# Phase 5.0 Fast Loader: Multi-Agent QA Framework

> **Target**: RFC-0006 Phase 5.0 Fast Loader  
> **Version**: v1.0  
> **Date**: 2026-01-02

---

## 🎯 Framework Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Leader (主编)                          │
│              Aggregation · Prioritization · Reporting           │
├─────────────────────────────────────────────────────────────────┤
│                              │                                   │
│   ┌──────────────────────────┼──────────────────────────┐       │
│   │                          │                          │       │
│   ▼                          ▼                          ▼       │
│ ┌───────────┐          ┌───────────┐          ┌───────────┐     │
│ │ Agent A   │          │ Agent B   │          │ Agent C   │     │
│ │ 激进派 QA  │          │ 保守派 QA  │          │ 安全专家   │     │
│ │ Edge Cases│          │ Core Flow │          │ Security  │     │
│ └───────────┘          └───────────┘          └───────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔴 Agent A: 激进派 QA (Edge Case Specialist)

### Philosophy
> **"Break it before users do."**  
> 专注边界条件、异常输入、极端场景。目标是找到设计盲点。

### Test Matrix

| ID | 测试场景 | 攻击向量 | 预期行为 | RFC 章节 |
|----|---------|---------|---------|---------|
| A-01 | **Bundle 边界大小** | 255.9MB / 256MB / 256.1MB | 255.9MB ✓, 256MB ✓, 256.1MB → 拒绝 | §3.5 |
| A-02 | **0 模块 Bundle** | 空 bundle.veloc | Fallback 或明确错误 | §2.10 |
| A-03 | **10000+ 模块** | 极大模块数量 | 性能退化可接受 | §2.5 |
| A-04 | **模块名极限** | 1000 字符模块名 | 正确处理或拒绝 | §2.5 |
| A-05 | **深度嵌套包** | `a.b.c.d...` (50 层) | 正确解析 | §2.5 |
| A-06 | **循环依赖图** | A→B→C→A | 检测并报错或打破循环 | §2.6 |
| A-07 | **Unicode 模块名** | `模块名_日本語.py` | 正确处理 | §2.5 |
| A-08 | **NaN/Inf in offset** | 篡改 index 中的 offset | Hash 验证失败 → fallback | §6.6 |
| A-09 | **Negative offset** | offset = -1 | 拒绝或 fallback | §2.5 |
| A-10 | **Overlapping modules** | 两个模块 offset 重叠 | 检测冲突 | §2.5 |

### 测试策略
```python
# A-01: Boundary size test
def test_bundle_size_boundary():
    """256MB hard limit validation"""
    sizes = [255.9 * MB, 256 * MB, 256.1 * MB]
    for size in sizes:
        bundle = create_bundle_of_size(size)
        if size <= 256 * MB:
            assert load_bundle(bundle).is_ok()
        else:
            assert load_bundle(bundle).is_err("BundleTooLarge")
```

---

## 🟢 Agent B: 保守派 QA (Core Flow Stability)

### Philosophy
> **"Golden path must never break."**  
> 确保核心功能在正常条件下 100% 可靠。

### Test Matrix

| ID | 测试场景 | 输入条件 | 预期结果 | RFC 章节 |
|----|---------|---------|---------|---------|
| B-01 | **基础 Bundle 加载** | 有效 bundle.veloc | 成功加载所有模块 | §2.4 |
| B-02 | **Import Hook 注册** | `velo run --fast` | VeloFinder 在 sys.meta_path[0] | §2.3 |
| B-03 | **Cache Hit 路径** | fingerprint 未变 | 直接使用缓存 bundle | §2.3 |
| B-04 | **Cache Miss 重建** | fingerprint 变化 | 自动触发 rebuild | §2.3 |
| B-05 | **Fallback 机制** | Bundle 损坏 | 自动 fallback 到标准 import | §2.10 |
| B-06 | **Native Extension** | 包含 .so 的项目 | .so 走 filesystem, 其他走 bundle | §2.9 |
| B-07 | **多 Python 版本** | 3.11 / 3.12 / 3.13 | 各自独立 bundle 路径 | §6.1 |
| B-08 | **多平台** | macOS / Linux | bundle 路径包含 abi_tag | §2.5 |
| B-09 | **Cold Start 性能** | 200 模块 × 20KB | ≥ 5x faster than traditional | §0 |
| B-10 | **Warm Cache 性能** | 重复运行 | 稳定性能，无退化 | §0 |

### 回归测试清单
```bash
# B-01 ~ B-10 必须在每次 PR 前全部通过
pytest tests/qa/phase5/test_core_flow.py -v --tb=short
```

---

## 🔵 Agent C: 安全专家 QA (Security Expert)

### Philosophy
> **"Trust nothing. Verify everything."**  
> 从攻击者视角审视每个安全边界。

### Threat Model

```
┌────────────────────────────────────────────────────────────────┐
│                      Attack Surface                             │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐    │
│  │ Filesystem  │    │   Bundle    │    │  Python Heap    │    │
│  │  (untrusted)│───▶│  Parsing    │───▶│  (marshal.loads)│    │
│  └─────────────┘    └─────────────┘    └─────────────────┘    │
│        │                   │                    │              │
│        ▼                   ▼                    ▼              │
│   [SEC-C01~03]        [SEC-C04~06]         [SEC-C07~08]       │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### Security Test Matrix

| ID | 威胁类型 | 攻击场景 | 防御验证 | RFC 章节 |
|----|---------|---------|---------|---------|
| **C-01** | **Symlink Bypass** | `/tmp/evil.veloc` 通过 symlink 加载 | Path canonicalization 阻止 | §2.17 |
| **C-02** | **World-Writable** | bundle 权限 0666 | 检测并拒绝 | §2.17 |
| **C-03** | **TOCTOU Race** | 验证后替换文件 | 全量 RAM 加载后验证 | §6.6 |
| **C-04** | **Hash Bypass** | 篡改 content_hash | SHA-256 不匹配 → 拒绝 | §6.6 |
| **C-05** | **CRC32 Collision** | 故意构造 CRC32 碰撞 | SHA-256 仍然检测 | §2.15.4 |
| **C-06** | **Magic Corruption** | 修改 "VELO" magic | 早期拒绝 | §2.5 |
| **C-07** | **Marshal DoS** | 构造深度递归对象 | marshal.loads 深度限制 | §2.17 |
| **C-08** | **Memory Exhaustion** | 声明 4GB 模块但只有 1KB | 预检 offset+size ≤ bundle_size | §3.5 |
| **C-09** | **Path Traversal** | 模块名 `../../../etc/passwd` | 模块名验证 | §2.5 |
| **C-10** | **Build Lock Race** | 多进程同时 rebuild | flock 确保原子性 | §3.4 |

### 关键安全测试代码
```python
# C-01: Symlink bypass test
def test_symlink_to_tmp_rejected():
    """Symlink pointing to /tmp must be rejected"""
    os.symlink("/tmp/malicious.veloc", "project/.velo/cache/bundle.veloc")
    result = velo_run("--fast", "main.py")
    assert "InsecureLocation" in result.stderr

# C-03: TOCTOU race test
def test_toctou_prevention():
    """File replacement after read should not affect loaded data"""
    # 1. Start load (block after read, before parse)
    # 2. Replace file content
    # 3. Resume load
    # 4. Verify: loaded content matches original (RAM-based)
```

### 安全检查清单 (Pre-Release Gate)

- [ ] **P0-SEC**: Symlink 攻击 (C-01)
- [ ] **P0-SEC**: TOCTOU 竞态 (C-03)
- [ ] **P0-SEC**: SHA-256 验证绕过 (C-04)
- [ ] **P1-SEC**: 权限检查 (C-02)
- [ ] **P1-SEC**: 内存耗尽 (C-08)

---

## 👔 Agent Leader: 主编 (Coordinator)

### Responsibilities

| 职责 | 描述 |
|-----|------|
| **Aggregation** | 汇总 A/B/C 三方测试结果 |
| **Prioritization** | 根据严重性和影响范围排序 defects |
| **Conflict Resolution** | 当 A 和 B 意见冲突时仲裁 |
| **Reporting** | 生成统一的 QA 报告 |
| **Sign-off** | 最终 QA 通过/不通过决策 |

### Decision Matrix

| Agent A 结果 | Agent B 结果 | Agent C 结果 | Leader 决策 |
|-------------|-------------|-------------|------------|
| ✅ Pass | ✅ Pass | ✅ Pass | **✅ Release Ready** |
| ⚠️ Issues | ✅ Pass | ✅ Pass | ⏸️ Evaluate edge case severity |
| ✅ Pass | ❌ Fail | ✅ Pass | **❌ Block Release** (核心流程不过) |
| Any | Any | ❌ Fail | **❌ Block Release** (安全问题优先) |

### Defect Severity Classification

| Level | 定义 | 处理 |
|-------|-----|------|
| **S0 Critical** | 安全漏洞 / 数据损坏 | 立即修复，Block Release |
| **S1 Major** | 核心功能失败 | 本版本修复 |
| **S2 Minor** | 边缘场景问题 | 下版本修复 |
| **S3 Trivial** | 优化建议 | Backlog |

### Reporting Template

```markdown
# Phase 5.0 Fast Loader QA Report

## Summary
| Agent | Pass | Fail | Skip | Total |
|-------|------|------|------|-------|
| A (Edge) | X | Y | Z | N |
| B (Core) | X | Y | Z | N |
| C (Security) | X | Y | Z | N |

## Blockers (S0/S1)
- [DEFECT-ID]: Description

## Known Issues (S2)
- [DEFECT-ID]: Description

## Sign-off
- [ ] Agent A: ___
- [ ] Agent B: ___
- [ ] Agent C: ___
- [ ] Leader: ___
```

---

## 🔄 Inter-Agent Collaboration Protocol

### Communication Flow

```
1. Leader 分发 RFC 解读
     ↓
2. A/B/C 独立设计测试用例 (24h)
     ↓
3. Leader Review + 去重 + 合并
     ↓
4. 并行执行测试
     ↓
5. 结果汇总到 Leader
     ↓
6. Leader 出具 Final Report
```

### Conflict Resolution Rules

1. **安全 > 稳定 > 边缘**：Agent C 的阻塞性问题优先级最高
2. **数据驱动**：争议用 benchmark 数据说话
3. **RFC 为准**：当意见分歧时，回归 RFC 原文

---

## 📋 Quick Reference: Test ID Mapping

| Prefix | Agent | Focus |
|--------|-------|-------|
| A-XX | Agent A | Edge cases, boundaries |
| B-XX | Agent B | Core flow, regression |
| C-XX | Agent C | Security, attack vectors |

---

**Document End**
