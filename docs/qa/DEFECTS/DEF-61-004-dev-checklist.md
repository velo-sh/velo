# DEF-61-004: Developer Handover Checklist

> **Parent**: [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md)
> **Type**: Developer Task Assignment
> **Estimated Hours**: 4.5h

---

## 📋 Task Summary

实现协议版本 Socket 隔离,解决升级后 30s 超时问题。

---

## ✅ Implementation Checklist

### Phase 1: Rust Side (2h)

- [ ] **1.1** 修改 `src/zygote/ipc.rs`
  - [ ] 导出 `PROTOCOL_VERSION` 常量
  - [ ] 实现 `get_socket_dir()` - 用户隔离目录
  - [ ] 实现 `is_socket_alive()` - 连接测试
  - [ ] 实现 `cleanup_stale_sockets()` - 清理旧 Socket
  - [ ] 修改 `default_socket_path()` - 带版本号

- [ ] **1.2** 修改 `src/zygote/mod.rs`
  - [ ] 在 `ZygoteLauncher::start()` 中调用 `cleanup_stale_sockets()`

### Phase 2: Python Side (1h)

- [ ] **2.1** 修改 `velo_zygote/main.py`
  - [ ] 添加 `get_socket_dir()` 函数
  - [ ] 添加 `get_versioned_socket_path()` 函数
  - [ ] 修改 `ZygoteServer` 使用新路径

### Phase 3: Edge Cases (1h)

- [ ] **3.1** 权限处理
  - [ ] 目录创建后设置 0700 权限
  - [ ] 验证权限设置成功

- [ ] **3.2** 路径长度
  - [ ] 检查路径 < 108 字符
  - [ ] 超长时回退到 `/tmp`

- [ ] **3.3** 错误处理
  - [ ] 清理时忽略权限错误
  - [ ] 目录不存在时优雅返回

### Phase 4: Verification (0.5h)

- [ ] **4.1** 运行 `cargo test`
- [ ] **4.2** 运行 `./scripts/benchmark_startup.sh`
- [ ] **4.3** 验证升级场景

---

## 📁 Files to Modify

| File | Changes |
|------|---------|
| `src/zygote/ipc.rs` | +4 functions, modify 1 |
| `src/zygote/mod.rs` | +1 call |
| `velo_zygote/main.py` | +2 functions, modify 1 |

---

## 🔗 Reference Documents

- [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md) - 完整设计
- [DEF-61-004-qa-review.md](./DEF-61-004-qa-review.md) - QA 测试规格

---

## ⚠️ Critical Implementation Notes

1. **权限**: 使用 `set_permissions` 后验证 mode 是否为 0700
2. **路径长度**: Unix Socket 限制 108 字符,macOS 深层 $TMPDIR 需回退
3. **错误处理**: `cleanup_stale_sockets()` 不能 panic

---

## 🎯 Acceptance Criteria

| AC | Description | Test |
|----|-------------|------|
| AC-1 | Socket 路径含版本号 | T2 |
| AC-2 | 用户隔离目录 | T5 |
| AC-3 | 连接测试判断 stale | T3 |
| AC-4 | 目录权限 0700 | T4 |
| AC-5 | Benchmark 通过 | Manual |
| AC-6 | 无回归 | CI |
| AC-7 | 路径长度 < 108 | T6 |
| AC-8 | 优雅错误处理 | T7 |

---

**Developer Sign-off**: [ ] Ready to implement
**Estimated Completion**: 4.5 hours
