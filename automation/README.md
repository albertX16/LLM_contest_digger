# automation/ — 本地自动化因子挖掘闭环（2024 1 分钟）

目标：在本地把“模板生成 → 遗传算法搜索 → Barra 正交回测 → 账本记录 → 结果总结”
整条投研链路自动化。LLM 使用 DeepSeek 双 Agent，搜索与评分在本地执行。
自 2026-08-03 起，挖掘数据从 2023 30m 改为 **2024 年 1 分钟**：原始 1m 按周块
缓存（服务端单次读取上限 200MB），再一次性聚合成日频特征面板供 GA 使用。
AIStudio 上传是显式可选外循环，最终提交始终由你手动完成。

## 架构

    planner agent (DeepSeek)         summarizer agent (DeepSeek)
          │ 2 exploit + 2 explore          ▲ 教训/反演候选
          ▼                                │
     四个独立 GA 搜索族 ──► 本地求值 ──► quick_fitness 粗筛
          ▲                                │
          └── MAP-Elites + 组件信用表 ◄────┘
                                      │
                                      ▼
                    去极值 → 标准化 → Barra/行业逐日残差化
                                      │
                                      ▼
                   A-score + RefSet + spanning + Elastic Net
                                      │
                                      ▼
                      ledger + 待提交比赛格式 notebook

系统采用 fail-closed 严格模式：已启用的 Agent、真实数据、十个 Barra 风格/行业
exposure、RefSet、完整评分或显式开启的平台上传任一失败，当前运行立即中止。
不会关闭组件、改用代理数据、把 raw 分数冒充中性化分数，或把失败候选记成低分继续。

## 用法

仅验证代码链路（显式合成 fixture，不代表真实投研结果）：

    .venv/bin/python automation/main.py --smoke --llm off --platform off

严格本地投研（2024 1m + DeepSeek + 本地正交回测，不连接 AIStudio）：

    .venv/bin/python automation/main.py --rounds 5 --platform off

注：DeepSeek 调用与 BigQuant 取数都需要外网权限，请在已授权的 macOS
Terminal 中启动（沙箱内会因 DNS 拦截而严格失败——这是预期行为，不是程序 bug）。
main.py 启动时先做 DeepSeek preflight 自检，失败会给出明确提示。

只在需要上传幸存 notebook 时显式连接 AIStudio：

    .venv/bin/python automation/main.py --rounds 3 --platform on

未加 --smoke 时固定使用真实数据。异常不会被转成成功退出码。

## 依赖与数据

- 真实取数：`bigalpha_2026_e2e_bar1m`（2024 全年），按周块下载缓存到
  `data_cache/dai_download/raw_1m_*.parquet`，再聚合为
  `data_cache/dai_download/daily_features_2024_1m.parquet`。
  缓存覆盖不完整/时间戳非日内/月份断档都会被拒绝命中。
- 全年 1m 约 5800 万行，从不整体载入内存：`iter_1m_chunks()` 逐块流式
  读取，`build_daily_features()` 每块处理完即释放；GA 只接触约 24 万行的
  日频特征面板（峰值内存约 200MB）。
- 默认 local_classic 模式从授权 bar 明确构造规模代理、Beta、动量、短反转、
  波动、非线性规模、流动性、价格水平和成交量风格控制。它用于本地正交回测，
  不会被标成官方 Barra。
- official_file 模式严格要求本地 exposure 文件包含
  SIZE/BETA/MOMENTUM/RESVOL/SIZENL/BTOP/LIQUIDTY/EARNYILD/GROWTH/LEVERAGE
  以及行业哑变量。候选与 RefSet 同时残差化后才进入 A/B 评分。
- DeepSeek key 路径由 configs/default.yaml 配置；Planner 与 Summarizer 维护各自记忆。
- 默认每轮规划四个互不重复的机制。有历史证据后严格分成两个 exploit 和两个
  explore；全新运行的第一轮没有逻辑上可引用的父代，因此显式作为四个 explore
  的 bootstrap，第二轮起若 archive 丢失则直接报错。
- 每个机制各跑一套 24 个体 × 20 代的 GA。MAP-Elites 的历史 elite 会作为
  exploit 父代和 Planner 证据；算子、字段、窗口、符号、combine、交叉/复制和
  mutation 动作的信用会从后续评分反向更新下一次抽样概率。
- `exploration_floor` 是算法明确保留的均匀探索质量，不是错误降级。运行状态、
  RNG、完整基因组精英和信用表会随轮次原子持久化，重启后续跑而非从头开始。
- Agent v2 Prompt 显式采用 Huatai 的单假设/样本隔离/失败归因、Liu et al. 的
  受约束 DSL/四类反馈/subsumption 警告和 OpenEvolve 的机器证据反馈；研究数字
  都带迁移限制，不被当成本项目阈值。
- 旧 planner.md 与 summarizer.md 保留但不再读取；它们包含错误的 2019–2023、
  1m/五档和空 RefSet 结论。可信记忆从 planner_v2.md / summarizer_v2.md 开始。
- 2024-01-01 至 2024-12-31 是当前自动训练窗口；2025 隐藏测试不触碰。
- 质量门控：2024 下半年作为确认窗口（confirm_split），确认段 RankIC t 值
  低于 confirm_t_min 的候选淘汰；同一轮不同机制候选日频相关性高于
  same_round_corr_max 时降级换选。

## 产物

- automation/runs/ledger.jsonl：append-only 实验账本，包含 preprocessing 证据。
- automation/runs/round_summary.jsonl：轮次汇总和下一轮诊断。
- automation/runs/search_state.json：可恢复的 MAP-Elites、GA/RNG、精英与诊断状态。
- automation/runs/component_credit.csv：便于人工查看的组件/遗传动作信用表。
- automation/runs/archive_elites.json：当前可供下一轮 exploit 使用的 archive 精英。
- automation/runs/待提交因子/：本地完整评分保留的比赛格式 notebook。
- automation/memory/：双 Agent 各自的长期记忆。

## 明确边界

- automation/ 是本地工作目录，不属于版本控制流程。
- 本地回测不依赖 AIStudio；平台上传默认关闭。
- 上传器只上传已验证 notebook，不运行伪 SQL、不冒充官方评分、不点击最终提交。
