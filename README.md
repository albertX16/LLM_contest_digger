[README.md](https://github.com/user-attachments/files/30277312/README.md)
# LLM_contest_digger
基于 LLM、Warm Start 遗传编程与分层评估漏斗的 AI 智能因子挖掘项目。项目围绕量化比赛中的 AI 智能赛道，构建从因子模板生成、公式变异、快速区段评估、因# AI 智能因子挖掘系统

本项目面向量化比赛中的 **AI 智能赛道**，目标是构建一个由大语言模型、遗传算法、强化学习式搜索策略和分层评估漏斗共同驱动的自动化因子挖掘工作流。

项目不以端到端深度预测模型为主线，而是聚焦于 **可解释因子生成、公式变异、快速筛选、因子池组合与研究记忆迭代**。核心思想是：让 LLM 提出研究假设和因子模板，让算法模块在受控空间内高效搜索，让数据评估器负责裁判，最后再由 LLM 总结结构规律并进入下一轮迭代。

## 项目目标

本项目希望回答一个问题：

> 如何让 AI 不只是“写几个因子公式”，而是深度参与因子的生成、搜索、筛选、组合和研究复盘？

为此，系统设计为一个闭环：

```text
官方规则 / 数据字段 / 算子库 / 历史研究记忆
        ↓
LLM Research Planner 生成因子模板与研究方向
        ↓
Warm Start Population 构造初始候选因子族
        ↓
RL Policy 学习字段、窗口、算子、模板的搜索偏好
        ↓
Genetic Programming 执行变异、交叉和保留
        ↓
Evaluation Funnel 做分层评估和少量完整回测
        ↓
Factor Pool & Combination 评估相关性与组合边际贡献
        ↓
LLM Summarizer 总结有效结构、失败模式和交互关系
        ↓
更新 Research Memory，进入下一轮
```

## 核心设计

### 1. LLM Research Planner

LLM 不负责直接打分，也不负责修语法。它的主要作用是提供高层研究假设：

- 根据官方规则、字段、算子和历史结果生成因子模板；
- 为每个模板提供经济逻辑解释；
- 给出模板级搜索边界，例如可用字段、窗口范围和最大复杂度；
- 在每轮结束后阅读实验摘要，更新研究记忆；
- 最后生成技术报告与 AI 参与过程说明。

第一轮 LLM 输入主要是规则、字段和算子；后续轮次会额外输入历史研究记忆、因子池状态、失败模式和组合结果。

### 2. Factor DSL 与规则过滤

因子公式使用受控 DSL 表达，避免 LLM 任意输出不可计算公式。该层由程序完成，不额外调用 LLM。

规则过滤包括：

- 字段合法性检查；
- 算子 arity 检查；
- 窗口范围检查；
- 表达式复杂度限制；
- 重复因子检查；
- 未来函数与规则违规检查。

非法候选直接丢弃或记录为失败样本，不再消耗回测资源。

### 3. Warm Start Genetic Programming

遗传算法不从全空间随机搜索，而是从 LLM 或历史高分因子总结出的模板开始。

遗传算法的作用不是“随机替换字段”这么简单，而是通过下面的循环让搜索逐渐靠近高质量结构：

```text
生成一代候选因子
→ 评估适应度
→ 保留高分个体
→ 高分个体更容易成为父代
→ 执行变异和交叉
→ 得到下一代候选因子
```

常见操作包括：

- 字段变异：`volume` → `amount`，`close` → `vwap`；
- 窗口变异：`20` → `10` / `40`；
- 方向变异：`rank(x)` → `-rank(x)`；
- 算子变异：`ts_mean` → `ts_std` / `ts_corr`；
- 结构交叉：将两个高分模板的子结构组合。

### 4. 强化学习式搜索策略

强化学习模块不写总结，也不解释因子逻辑。它负责根据历史数值奖励学习搜索动作偏好。

在第一版中，可以先实现为 bandit / Q-table 式策略：

```text
Q(template_family, action) = action 在该模板族中的历史收益
```

例如：

```text
Q(volume_price_divergence, replace_volume_with_amount)
Q(volume_price_divergence, change_window_to_10)
Q(pure_momentum, use_long_window)
```

这些 Q 值会影响下一轮遗传算法的采样概率，使系统不再均匀随机探索，而是优先尝试历史上更有效的动作。

### 5. Evo Funnel 分层评估漏斗

由于单个成品因子的完整回测可能耗时较长，本项目不对所有候选因子做全数据回测，而是采用分层漏斗：

```text
静态过滤
→ 典型市场区段快速评估
→ 中样本 RankIC / ICIR / 分组收益评估
→ 少量候选做完整回测
→ 因子组合评估
```

典型市场区段可以包括：

- 上行区段；
- 下行区段；
- 震荡区段；
- 高波动区段；
- 平稳区段。

这样可以在有限计算预算下优先保留更有潜力的因子。

### 6. Factor Pool 与因子组合

本项目不仅关注单因子表现，也关注因子之间的互补性。

候选因子进入因子池前，需要评估：

- 单因子 RankIC / ICIR；
- 分组收益单调性；
- 分市场区段稳定性；
- 与已有因子的相关性；
- 加入因子池后的边际贡献。

组合方法可从简单到复杂逐步推进：

- 等权组合；
- 按滚动 RankIC / ICIR 加权；
- Ridge 回归组合；
- ElasticNet 组合与筛选。

## LLM 在系统中的位置

本项目刻意限制 LLM 的使用位置，避免系统过慢或职责混乱。

LLM 主要出现在三个地方：

1. **每轮开始：研究规划与模板生成**
   - 输入规则、DSL、历史研究记忆、当前因子池；
   - 输出模板族、经济逻辑、搜索边界。

2. **每轮结束：研究记忆更新**
   - 输入本轮评估摘要、因子交互、组合结果；
   - 输出有效结构、失败模式、下一轮研究方向。

3. **最终阶段：报告生成**
   - 输出 AI 技术路线、实验过程、因子解释和局限性。

LLM 不负责：

- 语法校验；
- 单因子评分；
- 遗传算法的具体选择、交叉、变异；
- 强化学习策略更新；
- 因子组合模型训练。

## 预期目录结构

```text
.
├── README.md
├── requirements.txt
├── AIStudio_环境验证.ipynb
├── src/
│   ├── check_environment.py
│   └── hello_bigquant.py
├── scripts/
│   ├── aistudio_audit.sh
│   └── export_sample_data_remote.py
├── configs/
│   ├── official_rules.yaml
│   ├── factor_dsl.yaml
│   └── regime_slices.yaml
├── prompts/
│   ├── planner_prompt.md
│   └── summarizer_prompt.md
├── factors/
│   ├── templates/
│   └── generated/
├── evaluation/
│   ├── quick_eval.py
│   ├── mid_eval.py
│   └── full_backtest.py
├── search/
│   ├── genetic_programming.py
│   └── rl_policy.py
├── pool/
│   └── factor_pool.py
└── memory/
    └── research_memory.json
```

当前仓库仍处于早期构建阶段，上述目录会随着模块落地逐步补齐。

## 当前环境方案

BigQuant AIStudio 是云端开发环境。本项目当前采用混合工作流：

1. 在 AIStudio 中查询和导出比赛数据；
2. 将导出的数据缓存为 Parquet；
3. 用 `scp` / `rsync` 将数据切片同步到本地；
4. 本地负责代码开发、小样本实验和流程验证；
5. 需要更大规模计算时，再回到 AIStudio 或其他计算资源执行。

本地环境使用 Python 3.11 和 BigQuant SDK。环境检查：

```bash
.venv/bin/python src/check_environment.py
```

BigQuant 认证：

```bash
.venv/bin/bq auth configure
.venv/bin/bq auth status
```

AIStudio 远程环境审计：

```bash
bash scripts/aistudio_audit.sh
```

远程导出样例数据：

```bash
python scripts/export_sample_data_remote.py
```

## 参考文献

下面五篇论文是当前架构的主要方法来源。

1. [Large Language Models as Optimizers](https://arxiv.org/abs/2309.03409)  
   启发本项目中的 OPRO-style prompt iteration：将历史候选及其分数反馈给 LLM，让 LLM 生成下一轮更优候选。

2. [Feature Engineering for Predictive Modeling using Reinforcement Learning](https://arxiv.org/abs/1709.07150)  
   启发本项目将自动化因子构造视为 transformation graph 上的搜索问题，并用强化学习式策略学习哪些变换更值得尝试。

3. [RiskMiner: Discovering Formulaic Alphas via Risk Seeking Monte Carlo Tree Search](https://arxiv.org/abs/2402.07080)  
   启发本项目中的公式化 alpha 搜索、reward-dense MDP 思想，以及因子池中“高质量且低冗余”的组合目标。

4. [AlphaForge: A Framework to Mine and Dynamically Combine Formulaic Alpha Factors](https://arxiv.org/abs/2406.18394)  
   启发本项目从单因子挖掘走向因子池管理与动态组合，强调因子多样性和组合后表现。

5. [Alpha Mining and Enhancing via Warm Start Genetic Programming for Quantitative Investment](https://arxiv.org/abs/2412.00896)  
   启发本项目采用 Warm Start Genetic Programming：从已有模板或高分结构出发，在局部空间中做高效变异和交叉。

## 项目状态

当前阶段：

- 已明确 AI 智能因子挖掘的总体架构；
- 已搭建本地 Python / BigQuant SDK 基础环境；
- 已确认本地 API 直连数据并非当前主路线；
- 已转向 AIStudio 取数、本地开发、分层评估的混合流程；
- 下一步将落地 DSL、prompt、评估漏斗、遗传搜索和研究记忆模块。

## 免责声明

本项目仅用于量化研究与比赛实践，不构成任何投资建议。因子表现依赖数据区间、评估方式和市场环境，历史回测结果不代表未来收益。
子池组合到 LLM 研究记忆迭代的自动化流程，探索如何让大语言模型深度参与可解释量化因子的生成、筛选、优化与组合。
