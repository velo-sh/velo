# QA 交付清单模板 (Delivery Checklist Template)

每个测试任务完成后，使用此清单确保质量：

---

## Feature: [Feature Name]
## Phase: [X.Y]
## Date: [YYYY-MM-DD]

---

### Gate 1: 测试覆盖 (Test Coverage)

- [ ] **Happy Path 测试** - 正常用例全部通过
- [ ] **边界条件测试** - 边界值、空值、极限值
- [ ] **对抗性测试** - 尽力 BREAK！
  - [ ] 损坏的输入
  - [ ] 恶意输入
  - [ ] 并发/竞态条件
  - [ ] 资源耗尽

### Gate 2: CI 集成 (CI Integration)

- [ ] **本地测试通过** - `uv run python -m pytest tests/qa/ -v`
- [ ] **CI 测试通过** - GitHub Actions 绿灯
- [ ] **无 Flaky 测试** - 连续3次运行稳定

### Gate 3: 文档 (Documentation)

- [ ] **测试用例文档化** - docstring 清晰
- [ ] **已知限制记录** - 注释中说明
- [ ] **缺陷报告** - 发现的 bug 已记录

### Gate 4: 签收 (Sign-off)

- [ ] **Dev 验收测试通过** - `./scripts/test-phase1.5.sh`
- [ ] **QA 对抗测试通过** - 全部绿灯
- [ ] **性能指标达标** - 符合 DoD 要求
- [ ] **准备发布** - 无阻塞问题

---

## 签收人

| 角色 | 姓名 | 日期 | 签名 |
|------|------|------|------|
| QA | | | |
| Dev | | | |

---

## 缺陷摘要 (Defect Summary)

| ID | 严重程度 | 描述 | 状态 |
|----|----------|------|------|
| - | - | 无缺陷发现 | - |

---

**清单完成 = 准备交付 ✅**
