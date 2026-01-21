# GAP-001: Vibe Engine CLI Integration

> **Type**: Implementation Gap
> **Priority**: P1
> **Author**: Architect
> **Date**: 2026-01-21
> **Target**: Phase 8 Completion

---

## 1. Executive Summary

文档已更新为 `velo run --vibe` 形式，但代码实现仍使用独立子命令 `velo vibe`。需要重构 CLI 以对齐文档规范。

---

## 2. Current State vs Target State

| 项目 | 当前实现 | 目标状态 |
|:---|:---|:---|
| **主命令** | `velo vibe app.py` | `velo run --vibe app.py` |
| **别名** | 无 | `velo run --live app.py` |
| **端口配置** | `velo vibe app.py --port 9191` | `velo run --vibe --port 9191 app.py` |
| **CLI 路由** | `cmd_vibe()` 独立函数 | `cmd_run()` 内部分支 |

---

## 3. Files to Modify

### 3.1 `src/cli.rs`

**Current**:
```
"vibe" => cmd::cmd_vibe(&args),
```

**Target**: 删除 `vibe` 子命令，改为 `run` 命令的选项。

---

### 3.2 `src/cmd/run.rs`

**Changes Required**:
1. 添加 `--vibe` 和 `--live` 参数定义
2. 当启用 vibe 模式时，调用 `VibeEngine::new()` 而非标准执行流程
3. 转发 `--port` 参数到 Vibe Gateway

**Pattern**:
```rust
#[derive(Parser)]
struct RunArgs {
    /// Enable Vibe Coding mode (real-time hot reload)
    #[arg(long)]
    vibe: bool,
    
    /// Alias for --vibe
    #[arg(long)]
    live: bool,
    
    /// Vibe Gateway port (default: 8080)
    #[arg(long, default_value = "8080")]
    port: String,
    
    // ... existing args
}

fn cmd_run(args: RunArgs) -> Result<()> {
    if args.vibe || args.live {
        return run_vibe_mode(&args);
    }
    // ... existing run logic
}
```

---

### 3.3 `src/cmd/vibe.rs`

**Action**: 重构为内部模块函数，由 `cmd_run()` 调用，不再作为独立命令。

或者：保留文件，导出 `run_vibe_mode()` 供 `run.rs` 调用。

---

## 4. Verification

### 4.1 CLI Tests

```bash
# 新命令格式应该工作
velo run --vibe examples/hello.py
velo run --live examples/hello.py
velo run --vibe --port 9191 examples/hello.py

# 旧命令格式应该报错或显示迁移提示
velo vibe examples/hello.py  # Should show deprecation warning
```

### 4.2 Help Output

```bash
velo run --help
# Should show:
#   --vibe    Enable Vibe Coding mode (real-time hot reload)
#   --live    Alias for --vibe
#   --port    Vibe Gateway port (default: 8080)
```

---

## 5. Migration Strategy

### Option A: Hard Cut (Recommended)
- 直接移除 `velo vibe` 子命令
- 用户必须使用新格式
- 简洁，无技术债

### Option B: Deprecation Period
- 保留 `velo vibe` 但打印警告
- 2个版本后移除
- 对现有用户更友好

**Architect Recommendation**: Option A (Phase 8 刚发布，无历史用户)

---

## 6. Dependencies

- None (内部重构，不影响 Vibe Engine 核心逻辑)

---

## 7. Effort Estimate

| Task | Estimate |
|:---|:---|
| CLI 参数重构 | 30 min |
| run.rs 分支逻辑 | 30 min |
| 测试更新 | 30 min |
| 文档检查 | 15 min |
| **Total** | ~2 hours |

---

## 8. Sign-off

- [ ] Developer implements changes
- [ ] CLI tests pass
- [ ] `velo run --vibe` works end-to-end
- [ ] `velo vibe` removed or deprecated

---

**Architect Approval**: ✅ Ready for Development
