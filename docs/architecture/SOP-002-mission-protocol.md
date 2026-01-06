# SOP-002: 复杂任务执行协议 (The Mission Protocol)

> **级别**: TITANIUM (钛金级)
> **适用范围**: 架构部处理的所有 L3+ 级复杂任务 (Complex Missions)
> **核心哲学**: "我们不止交付结果，我们交付通往结果的必经之路。"

---

## 1. 第一阶段：法医级勘察 (Forensic Immersion)

**原则**: "不要相信用户的记忆，只相信代码的证据。" (Don't trust memory; verify code.)

在开始任何复杂任务之前，必须执行“白盒审计”：
1.  **历史回溯 (Chronological Deep Dive)**:
    *   读取 `git log` 和文件变更历史。
    *   **关键动作**: 寻找那些被“遗忘”的提交者和评审记录 (如 `RFC-0011` 中的 15 位专家)。
2.  **现场还原 (Scene Reconstruction)**:
    *   不仅仅是阅读代码，而是要*运行*它。
    *   **关键动作**: 建立 `Whitebox Audit` 文档，记录现状与预期的差异。
3.  **资产盘点 (Asset Inventory)**:
    *   检查现有文档 (`docs/`) 与实际代码的差距。
    *   **关键动作**: 识别“隐形资产”（如实际上存在但未被记录的加密审计流程）。

---

## 2. 第二阶段：众议院集结 (The Council Assembly)

**原则**: "一个人的智慧是脆弱的，二十人的视角是反脆弱的。"

不要试图独自解决复杂问题，必须召集(模拟)专家委员会：
1.  **角色识别 (Persona Excavation)**:
    *   根据任务属性，从 [Personas Catalog](./expert_review_personas_catalog.md) 中选取该任务所需的专家。
    *   *案例*: 发现 performance 任务不仅需要 HPC 专家，还需要 Accessibility 专家 (NO_COLOR)。
2.  **多视角对抗 (Adversarial Review)**:
    *   **Security**: "我怎么攻破它？"
    *   **Ops**: "凌晨3点炸了怎么办？"
    *   **Legal**: "这合规吗？"
3.  **全员共识 (Unanimous Consent)**:
    *   复杂决策必须获得所有相关专家的“有条件通过”。

---

## 3. 第三阶段：检察官验证 (The Prosecutor's Trial)

**原则**: "默认有罪 (Buggy) 推定，直到零 Mock 证明清白。"

验证过程必须带有敌意：
1.  **零 Mock 原则 (Zero-Mock)**:
    *   禁止在核心路径使用 Mock。必须在真实二进制 (`target/release`) 和真实内核上运行。
2.  **甚至更严 (Titanium Variance)**:
    *   如果现有标准不够严（如 500ms 重启），应当场升级标准（<50ms），而不是降低标准以通过测试。
3.  **证据留存 (Audit Report)**:
    *   必须生成不可篡改的审计报告 (Audit Report)，作为任务结束的唯一凭证。

---

## 4. 第四阶段：钛金级固化 (Titanium Crystallization)

**原则**: "如果不写进 SOP，这事就没发生过。"

任务的终点不是代码 Merge，而是知识的晶体化：
1.  **标准升级 (Standard Elevation)**:
    *   将本次任务中发现的“最佳实践”直接写入 `SOP-001` 或 `AGENTS.md`。
    *   *案例*: 将 "Council of 5" 升级为 "Grand Council of 20"。
2.  **物理实例化 (Physical Materialization)**:
    *   文档不能只停留在口头或临时文件。必须在 `docs/` 目录下建立永久文件。
    *   *案例*: 创建 `expert_review_personas_catalog.md`。
3.  **知识库同步 (KI Sync)**:
    *   更新 Agent 的长期记忆 (Knowledge Items)，确保下一次任务站在巨人的肩膀上。

---

**Last Updated**: 2026-01-06 (Created via The Grand Carpet Search)
