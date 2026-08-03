# 自动化系统更新日志（2026-08-01 → 2026-08-03）

## 2026-08-01：审计与严格化

- 定位 DeepSeek 搭建的 `automation/` 系统并逐模块审计，修复六处结构性缺口
  （错误缓存、forward return 跨股票风险、Planner 记忆未进提示词、MAP-Elites
  未接入主循环、平台阶段调用旧伪 SQL 渲染器等）；
- 固定边界：2023 训练窗（当时）、fail-closed 严格模式（任何必需组件失败立即
  中止，不降级、不妥协）；
- 本地经典风格残差化层落地（9 个 bar 衍生风格控制 + 逐日 OLS 残差化），
  补齐"Barra 正交"研究门槛；
- Planner/Summarizer v2 prompt：纳入 Huatai 单假设/隔离/失败归因、Liu 受约束
  DSL 与 subsumption 警告、OpenEvolve 反馈；旧 v1 memory 隔离；
- 三轮试运行（R1 保留 4、R2 保留 2），第一批 6 个 keep 因子改写并上传
  AIStudio。

## 2026-08-02：跨轮自进化与平台反馈闭环

- 每轮改为 4 个独立机制（有历史后 2 exploit + 2 explore），exploit 必须引用
  指定父因子，explore 必须无父代；
- MAP-Elites 真正参与下一轮（父代、GA seed、跨进程恢复）；持久化组件信用表
  （算子/字段/窗口/符号/combine/motif/变异动作），后验成绩反向更新抽样概率；
- search_state 原子持久化，断点续跑（Round 3 后改参数重启不丢状态）；
- 平台反馈接入：公榜分数按历史轨迹记录，领先因子序列长期维护；
- 修复 DeepSeek 空 content（官方 JSON mode + thinking high + 不设 max_tokens +
  含 JSON 示例的重试）；启动前 preflight 自检网络与 key；
- R3/R4/R5 候选人工改写为 main notebook 并上传（batch_001/002/003）。

## 2026-08-03：切换到 2024 1 分钟数据 + 质量与探索策略

- 挖掘数据从 2023 30m 切换为 **2024 全年 1 分钟**：周块缓存（解决服务端
  200MB 上限）、逐块流式聚合成 69 维日频特征面板（解决内存压力，
  峰值约 200MB，单轮 GA 秒级）；
- 新增确认窗口门控与同轮多样性门控；
- Prompt 层前沿引导：Planner 系统提示词写入前沿研究建议（LOB 形状/凸性、
  microprice 误差修正、日内动量、订单规模分解、分钟级特征库、多智能体辩论），
  并明确"允许失败、失败即换方向"；Summarizer 执行"失败即冻结"策略；
- 公榜分数再次更新（85A184EF 0.807 领先；D453 回升 0.782；5857CA18 0.768）；
- 2024 1m 首轮试跑（run_2024_1m_v1）：R1 保留 8、R2 保留 1；随后从 R3 续跑。
