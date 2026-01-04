# Phase 6.1 Serve & Analyze: Multi-Agent QA Framework

> **Target**: RFC-0010 Phase 6.1 Serve & Analyze  
> **Version**: v1.0  
> **Date**: 2026-01-04

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
| A-01 | **长路径边界** | 4096字符app路径 | 拒绝或处理 | §5.1.1 |
| A-02 | **Unicode输入** | 中文模块名 | 正确处理 | §5.2.2 |
| A-03 | **快速文件变更** | 100次/秒 | Debounce (300ms) | §4.4 |
| A-04 | **多app检测** | 3个FastAPI实例 | 选择第一个或报错 | §4.8 |
| A-05 | **工厂嵌套** | 类方法中的create_app | 检测或跳过 | §4.8 |

---

## 🟢 Agent B: 保守派 QA (Core Flow Stability)

### Philosophy
> **"Golden path must never break."**  
> 确保核心功能在正常条件下 100% 可靠。

### Test Matrix

| ID | 测试场景 | 输入条件 | 预期结果 | RFC 章节 |
|----|---------|---------|---------|---------|
| B-01 | **基础启动** | `velo serve` | 服务监听端口 | §4.1 |
| B-02 | **Health端点** | GET /health | 返回 200 OK | §5.1.1 |
| B-03 | **优雅关闭** | SIGTERM | 无孤儿进程 | §4.3 |
| B-04 | **FastAPI检测** | `app = FastAPI()` | 成功识别 | §4.8 |
| B-05 | **热重载** | 修改main.py | 自动重启 | §4.4 |
| B-06 | **Graph输出** | `analyze --graph` | ASCII图渲染 | §5.4 |

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
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐    │
│  │  CLI Input  │    │ File System │    │    Network      │    │
│  │ (untrusted) │───▶│  Watcher    │───▶│   Binding       │    │
│  └─────────────┘    └─────────────┘    └─────────────────┘    │
│        │                   │                    │              │
│        ▼                   ▼                    ▼              │
│   [SEC-61-INJ]        [SEC-61-PATH]        [SEC-61-NET]       │
└────────────────────────────────────────────────────────────────┘
```

### Security Test Matrix

| ID | 威胁类型 | 攻击场景 | 防御验证 | RFC 章节 |
|----|---------|---------|---------|---------|
| **C-01** | **命令注入** | `; rm -rf /` | Regex 验证阻止 | §12.3.2 |
| **C-02** | **路径遍历** | `../../../etc` | 规范化检查 | §12.3.1 |
| **C-03** | **PID竞态** | 并发写入 | O_EXCL 原子创建 | §5.1.1 |
| **C-04** | **环境劫持** | PYTHONPATH | 启动时清除 | §12.3.2 |

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

---

## 📋 Quick Reference: Test ID Mapping

| Prefix | Agent | Focus |
|--------|-------|-------|
| EDGE-61-* | Agent A | Edge cases, boundaries |
| CORE-61-* | Agent B | Core flow, regression |
| SEC-61-* | Agent C | Security, attack vectors |
| CHAOS-61-* | Leader | Brutal stress tests |

---

## 📊 Test File Mapping

| Test File | Agent | Test Count |
|-----------|-------|------------|
| `test_agent_a_edge.py` | A | 18 |
| `test_agent_b_stability.py` | B | 17 |
| `test_agent_c_security.py` | C | 17 |
| `test_leader_brutal.py` | Leader | 8 |

---

**Document End**
