# 自动化投研系统（automation/）工作流

**快照日期：** 2026-08-03

本文描述当前已在本地运行的自动化因子挖掘闭环（代码在 `automation/`），
与仓库根目录的 Mission Briefing（总体设计）互补。两者不一致时以本文 +
`automation/` 代码为准。

## 1. 系统定位

BigAlpha 2026 AI 因子赛道。系统目标不是端到端预测模型，而是可持续迭代的
因子研发闭环：LLM 提出研究机制 → 遗传算法在受约束 DSL 内搜索 → 本地
经典风格残差化 + 拥挤度/增量检验 → 账本记录 → 少量候选改写为可提交
notebook → 上传 AIStudio 由人工评估 → 平台反馈回灌下一轮。

## 2. 架构

```text
DeepSeek Planner（每轮 4 个独立机制：有历史后固定 2 exploit + 2 explore）
        ↓ 每个机制独立 GA 搜索（种群 16 × 5 代；算子/字段/窗口按历史信用加权）
        ↓ quick_fitness 粗筛
        ↓ 完整三级联评分：去极值→标准化→9 个本地经典风格逐日残差化
          →RefSet 相关门控→联合 spanning→滚动 Elastic Net
        ↓ append-only ledger + Summarizer（失败即冻结策略）
        ↓ MAP-Elites archive + 组件信用表 原子持久化（断点续跑）
        ↓ keep 候选 → agent_rewrite_queue/*.factor.json（待 Agent 改写提交）
```

关键文件：

- 入口：[`automation/main.py`](../automation/main.py)
- 轮次编排：[`automation/loop/run_round.py`](../automation/loop/run_round.py)
- Planner / Summarizer：[`automation/agents/planner.py`](../automation/agents/planner.py)、
  [`automation/agents/summarizer.py`](../automation/agents/summarizer.py)
- 1 分钟数据与日频特征面板：[`automation/panel/fetch_1m.py`](../automation/panel/fetch_1m.py)、
  [`automation/panel/daily_features.py`](../automation/panel/daily_features.py)
- 参数：[`automation/configs/default.yaml`](../automation/configs/default.yaml)
- 状态与产物：[`automation/runs/`](../automation/README.md)（search_state / ledger /
  round_summary / component_credit / agent_rewrite_queue）

## 3. 数据（2026-08-03 起：2024 年 1 分钟）

- 数据表 `bigalpha_2026_e2e_bar1m`（已授权），2024-01-01 至 2024-12-31；
- 服务端单次读取上限 200MB，因此按**周块**下载缓存（约 130MB/块，断点续传，
  春节/五一/国庆休市周按合法空缓存处理）；
- 全年约 5800 万行从不整体载入：逐块流式读取，聚合成 **69 个日频特征**
  （日内已实现波动率、VWAP 偏离、首/尾 30 分钟收益、尾盘量额份额、三档盘口
  快照与全天均值/波动、队列陡峭度、档位价差、microprice 溢价等）；
- GA 只接触约 24 万行日频面板，峰值内存约 200MB；
- 2025 为隐藏测试，自动流程永不触碰。

## 4. 质量门控（已落地）

1. **确认窗口门控**：2024 拆成搜索/确认两段（7 月 1 日分界），确认段日频
   RankIC t 值 < 1.5 的候选直接淘汰（防只在搜索段成立的过拟合信号）。
2. **同轮多样性门控**：同一轮不同机制候选的日频相关 > 0.6 时降级换选
   （防同族复制，如 R4 的 ask order layering 事件重演）。
3. **平台反馈后验化**：公榜快照按历史轨迹记录（`prior_reported_scores`），
   tier/ordinal_rank 按最新快照重排，`confirmed_retire` 只保留多次垫底者；
   反馈以独立后验信号更新 GA 组件信用。
4. **失败即冻结**：探索族一旦失败即冻结该方向，预算留给更多不同的新机制；
   只有明确 keep 或平台验证过的方向才允许 continue/repair。

## 5. 提交链路

- 自动程序只产出 `.factor.json` 规格（机制、genome 表达式、指标、淘汰原因），
  不自动生成提交代码；
- 交互式 Agent 按 AIStudio 已实测通过的模板改写为单 `main(datasources,
  start_date, end_date)` notebook（数据只能来自 `datasources["bar1m"]`，
  SQL 精确还原 8 根 30m bar，股票池左连接，返回 date/instrument/factor）；
- 通过外部 Edge 9222 CDP 上传到
  `/home/aiuser/work/automation_submissions/batch_NNN_round_NNN/`，
  远端 SHA-256 校验；上传 ≠ 平台评测 ≠ 最终提交。

## 6. 运行方式

```bash
# 冒烟（合成数据，不联网）
.venv/bin/python automation/main.py --smoke --llm off --platform off

# 真实 2024 1m 研究（需联网权限，外部 Terminal 启动）
./scripts/run_research.sh --rounds 5 --platform off \
    --run-dir automation/runs/run_2024_1m_v1

# 进度监督（产物驱动，无需 ps）
.venv/bin/python scripts/supervise_research.py --run-dir automation/runs/run_2024_1m_v1

# 全年 1m 数据下载与特征面板构建（一次性后台任务）
.venv/bin/python scripts/download_1m_2024.py
```

依赖：BigQuant SDK（取数/缓存）、DeepSeek API（Planner/Summarizer）、
`bigalpha2026_main_src` 的 ledger 校验器（仅本地运行需要）。
