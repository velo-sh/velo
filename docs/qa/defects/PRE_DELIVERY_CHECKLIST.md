# 📋 Phase 6.0 Pre-Delivery Checklist (致开发)

> **请在提交任何修复之前，确保以下所有测试 100% 通过。**
> 这是 QA 强制门禁，任何失败都将导致交付被 REJECT。

---

## 🚨 必跑命令 (MUST RUN BEFORE DELIVERY)

```bash
# 1. 重新编译 Release 版本
cargo build --release

# 2. 运行 Rust 单元测试 (89 tests)
cargo test --lib

# 3. E2E Golden Path 正确性验证 (9 tests, 三大框架)
uv run pytest tests/qa/test_e2e_golden_path.py -v

# 4. Phase 6.0 Agent 全套测试 (边缘/稳定性/安全)
uv run pytest tests/qa/test_phase6_*.py -v

# 5. Enterprise 性能基准 (可选，但强烈建议)
python3 benchmark_enterprise.py --fastapi --flask --django
```

---

## ✅ 期望结果

| 命令 | 期望结果 |
|:---|:---|
| `cargo test --lib` | `89 passed` |
| `test_e2e_golden_path.py` | `9 passed` (GOLD-001/002/003 × 3 frameworks) |
| `test_phase6_*.py` | 全部 PASSED 或 XFAIL (无 FAILED) |

---

## 🛑 当前阻塞问题 (DEF-60-007)

**Bundle Content Hash Mismatch**:
- `velo run --fast` 因 BLAKE3 哈希校验失败而拒绝所有 Bundle。
- 可能原因：非确定性序列化、padding 问题、或 header/body 写入顺序错误。
- 请在修复后运行 `test_e2e_golden_path.py` 验证。

---

## 📞 联系 QA

如有疑问，请直接联系 QA Lead 或在本分支上创建 Draft PR 让我们提前审核。

**QA Working Group**
