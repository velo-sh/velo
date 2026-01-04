# DEF-61-004: QA Handover Checklist

> **Parent**: [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md)
> **Type**: QA Task Assignment
> **Total Test Cases**: 17

---

## 📋 QA Summary

验证协议版本 Socket 隔离实现,确保升级/降级场景无问题。

---

## ✅ Test Implementation Checklist

### Phase 0: Test Setup

- [ ] **0.1** 创建测试文件 `tests/qa/test_def_61_004_socket_isolation.py`
- [ ] **0.2** 导入必要模块 (pytest, mock, tempfile)
- [ ] **0.3** 设置 fixtures

### Phase 1: Core Tests (T1-T5)

- [ ] **T1** 版本升级清理旧 Socket
- [ ] **T2** Socket 路径格式正确
- [ ] **T3** 运行中 Socket 不被删除
- [ ] **T4** 目录权限 0700
- [ ] **T5** 多用户隔离

### Phase 2: Edge Case Tests (T6-T10)

- [ ] **T6** 长 $TMPDIR 路径回退
- [ ] **T7** 权限错误优雅处理
- [ ] **T8** 并发启动无竞态
- [ ] **T9** 符号链接攻击防护
- [ ] **T10** 磁盘空间不足

### Phase 3: Regression Tests (REG-001 to REG-004)

- [ ] **REG-001** 全新安装 v0.6.2
- [ ] **REG-002** 升级 v0.6.1 → v0.6.2
- [ ] **REG-003** 降级 v0.6.2 → v0.6.1
- [ ] **REG-004** 多用户并行

### Phase 4: Performance Tests

- [ ] **AC-9** `get_socket_dir()` < 1ms
- [ ] **AC-10** `cleanup_stale_sockets()` < 100ms
- [ ] **AC-11** Socket 连接 < 5ms

---

## 📁 Test Files

| File | Tests |
|------|-------|
| `tests/qa/test_def_61_004_socket_isolation.py` | T1-T10, REG-001-004 |
| `tests/qa/test_def_61_004_performance.py` | AC-9, AC-10, AC-11 |

---

## 🔗 Reference Documents

- [DEF-61-004-qa-review.md](./DEF-61-004-qa-review.md) - 完整 pytest 规格
- [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md) - 设计文档

---

## 🧪 Test Matrix

### Version Compatibility

| Scenario | New CLI | Old CLI | Expected |
|----------|---------|---------|----------|
| New Zygote only | ✅ Connect | ❌ Fail | Isolation |
| Old Zygote only | ❌ Fail | ✅ Connect | Isolation |
| Both running | ✅ Use new | ✅ Use old | Coexist |

### Platform Coverage

| Platform | Required |
|----------|----------|
| macOS (Intel) | ✅ |
| macOS (ARM) | ✅ |
| Linux (Ubuntu) | ✅ |
| Linux (Alpine) | Optional |

---

## ⚠️ Test Environment Requirements

1. **两个 Velo 版本**: v0.6.1 (JSON) 和 v0.6.2 (MessagePack)
2. **多用户测试**: 需要两个不同 UID 的用户
3. **权限测试**: 需要 root 权限创建受限目录

---

## 🎯 Verification Criteria

| AC | Description | Test(s) | Pass Criteria |
|----|-------------|---------|---------------|
| AC-1 | 版本号路径 | T2 | 路径含 `zygote-v1.sock` |
| AC-2 | 用户隔离 | T5 | 路径含 `velo-{UID}/` |
| AC-3 | 连接测试 | T1, T3 | 活 Socket 不删除 |
| AC-4 | 权限 0700 | T4 | `stat` 验证 |
| AC-5 | Benchmark | Manual | 无 30s 超时 |
| AC-6 | 无回归 | CI | 182 tests pass |
| AC-7 | 路径 < 108 | T6 | 长路径回退 |
| AC-8 | 错误处理 | T7 | 无 panic |
| AC-9 | dir < 1ms | Perf | benchmark |
| AC-10 | cleanup < 100ms | Perf | benchmark |
| AC-11 | connect < 5ms | Perf | benchmark |

---

## 📊 Test Execution Order

```
1. Unit Tests (T1-T5)        ← Developer 完成后立即执行
2. Edge Case Tests (T6-T10)  ← Developer 修复后
3. Regression Tests          ← 合并前
4. Performance Tests         ← 最后
```

---

**QA Sign-off**: [ ] Ready to test
**Blocked by**: Developer implementation complete
