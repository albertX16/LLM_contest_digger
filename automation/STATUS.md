# 自动化 Mining 状态（2026-08-02）

## 2026-08-03 更新：切换到 2024 1 分钟数据

- 挖掘数据从 2023 30m 改为 2024 全年 1 分钟（bigalpha_2026_e2e_bar1m，
  已授权）；原始 1m 按周块缓存（服务端单次读取上限 200MB），
  再聚合成日频特征面板 `data_cache/dai_download/daily_features_2024_1m.parquet`。
- 内存方案：全年 1m（约 5800 万行 / 8GB）从不整体载入；iter_1m_chunks
  逐周块流式读取，build_daily_features 每块处理完即释放；GA 只接触
  约 24 万行的日频特征面板，峰值内存约 200MB，单轮 GA 约 1 秒。
- 春节休市周（2024-02-12..02-18）查询返回空，按合法空缓存处理。
- 质量门控新增：confirm_split 确认窗口 RankIC t 值门控（默认 1.5）、
  同轮跨机制候选日频相关性上限（默认 0.6）。
- 公榜反馈按历史轨迹更新：prior_reported_scores 保留全部观测，
  tier/ordinal_rank 按最新快照重排；confirmed_retire 只保留多次垫底者。
- DeepSeek 客户端：不发送 max_tokens（输出不限）、thinking high + 官方
  JSON mode；空 content 用含 JSON 示例的指令重试；启动前 preflight 自检
  网络与 key（沙箱断网会给出明确的操作提示）。

### 正确入口（1m 模式）

代码链路验收（合成数据，不联网）：

    .venv/bin/python automation/main.py --smoke --llm off --platform off

真实 2024 1m 本地研究（需联网权限，外部 Terminal 启动）：

    .venv/bin/python automation/main.py --rounds 1 --platform off

先下载 2024 全年 1m 并构建特征面板（一次性后台任务）：

    .venv/bin/python scripts/download_1m_2024.py

## 来源记录

已定位并复核 DeepSeek 兼容会话，主要链路包括：

- 019fbd03-c6b2-7f43-bce9-005b92e2c984：初始 Flash/xhigh 搭建。
- 019fbd90-da66-7540-a051-98133aad579d：Flash/high 续作。
- 019fbde9-a338-7262-9f43-753ec1d5676b：Flash 到 Pro 的长续作。

旧会话建立的目标架构是：双 Agent 规划/总结、类型化因子搜索、GA 与
MAP-Elites、本地三级联评分、append-only ledger、可选 AIStudio 外循环。

## 已验证可用

1. 2023 真实 30m 数据缓存：
   - 1,933,048 行；
   - 242 个交易日；
   - 1,201 个标的；
   - 8 个时点：10:00、10:30、11:00、11:30、13:30、14:00、14:30、15:00；
   - 28 列，含三档盘口和逐档委托笔数。
2. 错误缓存会被拒绝：
   - 文件名声称 2019–2023、实际只有部分 2023；
   - Q1/Q2Q4 文件把 30m timestamp 压成纯日期；
   - 新校验要求真实日内时刻、请求范围端点和逐月连续性。
3. 因子 DSL：
   - 算子 arity、字段和窗口严格校验；
   - evaluator 与 notebook compiler 语义对齐；
   - GA 只在实际存在的字段/算子上搜索；
   - 指纹去重和类型安全 mutation/crossover。
4. 本地风险正交回测：
   - local_classic 明确构造九个 bar 衍生传统风格控制；
   - 逐日执行去极值、标准化、横截面 OLS 残差化；
   - 再执行 A-score、RefSet corr gate、联合 spanning 和滚动 Elastic Net；
   - official_file 是独立严格模式，不会用本地代理悄悄替代官方 exposure。
5. 真实候选验收：
   - 简单 OBI 在风险残差化后 RankIC 约 0.0275、RankIC IR 约 0.835；
   - 因与 RefSet 的 OBI 基线相关 1.00，被 corr gate 正确淘汰；
   - preprocessing 记录 neutralized=true、9 exposures、222 个回归日。
6. 双 Agent v2：
   - Prompt 明确吸收 Huatai、Liu et al.、OpenEvolve 的可迁移方法及限制；
   - 字段有自然语言释义，算子有 arity/语义；
   - Planner 要求机制、事前符号、父机制交互、falsifier、消融和 kill criteria；
   - Summarizer 先由程序分类，再做证据绑定反思；
   - wrong-sign 不允许裸翻转，必须形成新机制并在未触碰窗口确认；
   - 旧 v1 memory 保留但已隔离，不再输入 Agent。
   - DeepSeek Flash 真实 Planner 验收通过：输出 1 个 prototype 与 4 个
     variant genomes，全部通过字段、arity、非嵌套 DSL、block 数和搜索空间校验；
   - DeepSeek Flash 真实 Summarizer 验收通过：把高 IC/t/PFS 但 RefSet
     corr=1.00 的 OBI 明确判为 crowded_duplicate，并冻结该族；
   - 两次验收均 save_memory=false，没有把测试输出写入长期记忆。
7. 严格失败语义：
   - 已启用 Agent、数据、风险 exposure、RefSet、评分和显式平台上传失败均抛错；
   - 不关闭组件、不改成 raw 评分、不把异常候选伪装成低分继续。
8. 测试：
   - 21 项本地测试全部通过；
   - 合成端到端 smoke 完成；
   - DeepSeek API 密钥有效，配置的 deepseek-v4-flash 与 deepseek-v4-pro 均在模型列表。
9. 跨轮自进化（2026-08-02 补齐）：
   - 默认每轮四个独立机制；有 archive 后固定 2 exploit + 2 explore，候选评分额度
     也按两条轨道对半分，并保证每个机制至少一个候选；
   - exploit 必须引用调度器指定的历史 factor_id，explore 必须无父代且提出新机制；
   - MAP-Elites 不再是只写不用：其精英会进入下一轮 Planner 证据与 GA seed；
   - 持久化 component credit 覆盖 op、field、window、sign、combine、block motif、
     mutation action/intensity 与 crossover/clone；后代相对父代改善及完整三级联结果
     都会反向更新信用；
   - search_state.json 原子保存 archive、RNG、warm-start、诊断与信用表；新进程会从
     last_completed_round+1 继续，不再把重启误当 Round 1；
   - 隔离 smoke 已连续跑 Round 1–2，再重启进程自动续跑 Round 3–4；状态显示 53 个
     MAP cells、10 类信用项和连续轮次 [1, 2, 3, 4]；Round 4 的一个 stage-1
     panel contract 缺失率失败被明确记为 retire，任何进入 stage 2/3 却未风险残差化
     的结果仍会整轮中止。

## 平台边界

- platform=off：完整本地研究与正交回测，不连接 AIStudio。
- platform=on：只上传已经通过本地评分的 notebook。
- 上传、线上运行评估、比赛最终提交是三个不同状态。
- 当前上传器绝不点击最终提交，也不把上传成功写成官方评分成功。

## 尚未宣称完成的事项

1. 未自动运行 AIStudio 官方评估并读取结果。2023 本地数据量可控，因此当前不需要
   以平台替代本地回测；若启用线上评估，必须单独实现/验证其运行与结果读取状态，
   仍与最终提交隔离。
2. official_file 模式需要人工从 AIStudio 导出 bigalpha_2026_exposure；本地 SDK
   对该表返回 Unauthorized。默认 local_classic 不冒充官方 Barra。
3. 2024 保持人工专用，自动流程未触碰。

## 正确入口

代码链路验收：

    .venv/bin/python automation/main.py --smoke --llm off --platform off

真实 2023 本地研究：

    .venv/bin/python automation/main.py --rounds 1 --platform off

只有明确需要上传候选 notebook 时：

    .venv/bin/python automation/main.py --rounds 1 --platform on
