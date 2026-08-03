"""Agent A: research-grounded, executable factor-family planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm_client import LLMClient
from automation.search.genome import (
    COMBINE_OPS,
    RAW_FIELDS,
    SUPPORTED_OPS,
    Genome,
    normalize_search_space,
    validate_genome,
)


FIELD_DESCRIPTIONS = {
    "open": "本根30m开盘价", "high": "本根30m最高价",
    "low": "本根30m最低价", "close": "本根30m收盘价",
    "volume": "本根成交量", "amount": "本根成交额",
    "deal_number": "本根成交笔数", "adjust_factor": "复权因子",
    "bid_price1": "买一价", "bid_price2": "买二价", "bid_price3": "买三价",
    "ask_price1": "卖一价", "ask_price2": "卖二价", "ask_price3": "卖三价",
    "bid_volume1": "买一挂单量", "bid_volume2": "买二挂单量",
    "bid_volume3": "买三挂单量", "ask_volume1": "卖一挂单量",
    "ask_volume2": "卖二挂单量", "ask_volume3": "卖三挂单量",
    "bid_num_orders1": "买一委托笔数", "bid_num_orders2": "买二委托笔数",
    "bid_num_orders3": "买三委托笔数", "ask_num_orders1": "卖一委托笔数",
    "ask_num_orders2": "卖二委托笔数", "ask_num_orders3": "卖三委托笔数",
    # ---- 2024 1m -> 日频特征面板（每日由 240 根 1m bar 聚合）----
    "vwap": "日成交量加权均价 amount/volume",
    "avg_trade_size": "日均单笔成交额 amount/deal_number",
    "ret_open_close": "日开盘到收盘收益 close/open-1",
    "ret_open_vwap": "日开盘到VWAP收益 vwap/open-1",
    "ret_close_vwap": "日收盘相对VWAP收益 close/vwap-1",
    "first30m_ret": "开盘后30分钟收益（10:00 收盘价/开盘价-1）",
    "last30m_ret": "尾盘30分钟收益（收盘价/14:31开盘价-1）",
    "am_ret": "上午时段收益（11:30收盘价/开盘价-1）",
    "pm_ret": "下午时段收益（收盘价/13:01开盘价-1）",
    "close_pos_in_range": "收盘价在当日高低区间中的位置 (close-low)/(high-low)",
    "volume_first30m_share": "开盘30分钟成交量占全天比例",
    "volume_last30m_share": "尾盘30分钟成交量占全天比例",
    "volume_am_share": "上午成交量占全天比例",
    "amount_last30m_share": "尾盘30分钟成交额占全天比例",
    "deal_number_last30m_share": "尾盘30分钟成交笔数占全天比例",
    "rv_1m": "1分钟收益年化已实现波动率（std*sqrt(240)）",
    "rv_am": "上午1分钟收益波动率",
    "rv_pm": "下午1分钟收益波动率",
    "mid_price": "收盘时点买卖一价中点 (bid1+ask1)/2",
    "spread": "收盘时点相对买卖价差 (ask1-bid1)/mid",
    "spread_bps": "收盘时点价差（基点）",
    "obi": "收盘时点订单簿失衡 (bid_v1-ask_v1)/(bid_v1+ask_v1)",
    "oci": "收盘时点委托笔数失衡 (bid_n1-ask_n1)/(bid_n1+ask_n1)",
    "depth1": "收盘时点一档深度 bid_v1+ask_v1",
    "depth_all": "收盘时点三档总深度",
    "bid_ask_vol_ratio1": "收盘时点买一挂单量/卖一挂单量",
    "bid_ask_vol_ratio_all": "收盘时点三档买量/三档卖量",
    "queue_imbalance_ask": "卖二委托笔数/卖一委托笔数（卖单队列陡峭度）",
    "queue_imbalance_bid": "买二委托笔数/买一委托笔数（买单队列陡峭度）",
    "price_gap_ask": "卖二价-卖一价（卖单档位价差）",
    "price_gap_bid": "买一价-买二价（买单档位价差）",
    "microprice": "收盘时点微观价格 (bid1*ask_v1+ask1*bid_v1)/(bid_v1+ask_v1)",
    "microprice_premium": "微观价格相对收盘价溢价 microprice/close-1",
    "avg_bid_volume1": "全天买一挂单量均值",
    "avg_ask_volume1": "全天卖一挂单量均值",
    "avg_bid_num_orders1": "全天买一委托笔数均值",
    "avg_ask_num_orders1": "全天卖一委托笔数均值",
    "avg_obi": "全天订单簿失衡均值",
    "std_obi": "全天订单簿失衡波动",
    "avg_oci": "全天委托笔数失衡均值",
    "avg_spread_bps": "全天相对价差均值（基点）",
}

OPERATOR_SPECS = {
    "raw": "raw(field): 原字段",
    "spread": "spread(): (ask1-bid1)/mid",
    "mid_price": "mid_price(): (ask1+bid1)/2",
    "order_book_imbalance": "order_book_imbalance(): (bid_volume1-ask_volume1)/(两者之和)",
    "order_count_imbalance": "order_count_imbalance(): 买卖一档委托笔数失衡",
    "depth": "depth(): bid_volume1+ask_volume1",
    "avg_trade_size": "avg_trade_size(): amount/deal_number",
    "return": "return(field, window=2..60): 标的内滞后收益",
    "volatility": "volatility(field, window=2..60): 标的内滚动收益波动",
    "rolling_mean": "rolling_mean(field, window=2..60)",
    "rolling_std": "rolling_std(field, window=2..60)",
    "rolling_sum": "rolling_sum(field, window=2..60)",
    "ewm": "ewm(field, window=2..60): 指数移动平均",
    "diff": "diff(field): 标的内一阶差分",
    "pct_change": "pct_change(field): 标的内一期变化率",
    "ratio": "ratio(field_a, field_b)",
    "difference": "difference(field_a, field_b)",
    "product": "product(field_a, field_b)",
    "clip": "clip(field, lo=-3, hi=3)",
}

RESEARCH_PRIORS = """研究约束（引用的是方法，不是可直接搬用的收益结论）：
1. Huatai《Self-Evolving Skill》(2026-05-25)：每个独立提案只改变一个主要机制；
   固定执行器与可搜索配置分离；发现/确认/最终留出隔离；失败必须归因。
   其 validation→test 传递有限，不能把发现窗改善当成稳健结论。
2. Liu et al. SSRN (2026-04)：受约束 DSL、事前方向、四类反馈和交互机制有效；
   159 个显著方案经同族赛马只剩 38，且 30/38 被至少一个基准模型吸收，
   所以“构造新颖”不等于“内容正交”。failure-inversion 标签命中率 64%
   来自美国年度会计因子，不能当作本项目翻转符号后的成功概率。
3. OpenEvolve：父代 + 精英启发 + 可执行反馈 + return-space MAP-Elites；
   代码形状多样性不能替代收益空间正交性。
"""

FRONTIER_SUGGESTIONS = """前沿研究建议（只作为 explore 轨“去哪里找新机制”的起点，
不是照抄配方；允许失败、失败即换方向，鼓励真正崭新的尝试）：
1. LOB 形状与凸性（Limit Order Book Shape and Return Distribution, SSRN 2024）：
   ask/bid 两侧斜率比驱动收益均值与偏度，高档/低档斜率比驱动方差与尾部风险。
   可用字段：queue_imbalance_ask/bid（队列陡峭度）、price_gap_ask/bid（档位价差）、
   bid_ask_vol_ratio_all、depth_all、avg_spread_bps。建议构造“盘口形状”类机制，
   例如买卖两侧委托笔数坡度之比，而不是再回到一档 OBI。
2. microprice 误差修正（Stoikov microprice；arXiv:2411.13594）：微观价格是
   结合档位失衡的价格估计。可用字段：microprice_premium、avg_obi/std_obi、
   avg_oci、avg_spread_bps。建议探索微观价格溢价与价量信号的非平凡交互。
3. 日内动量（Heston, Korajczyk & Sadka 2010，A 股/英/巴复现）：上午强度预测
   下午与次日。可用字段：first30m_ret、am_ret、pm_ret、rv_am/rv_pm、
   volume_first30m_share。建议构造“上午强度 → 次日反转/延续”类机制。
4. 订单规模/资金流分解（CFRN 实证：小中单净买预测次日收益，机构单不平衡更强）：
   可用字段：avg_trade_size、deal_number、amount_last30m_share、
   deal_number_last30m_share。建议表达“参与度/拆单”机制；amount 与 volume
   不是同一尺度，不能混用。
5. 分钟级特征库（Huatai“逐鹿 ALPHA”分钟因子、Alpha158/Factor Zoo）：
   分钟频率上的 RV、VWAP 偏离、波动形态经机器学习有显著预测力；本面板的
   rv_1m/rv_am/rv_pm、ret_close_vwap、close_pos_in_range 就是其日频化版本，
   可组合出“波动调整后的动量/反转”等机制。
6. 多智能体辩论因子挖掘（FactorMAD, ACM 2024）：强调机制-公式一致性与可批判性；
   explore 提案必须能被一句话反驳（falsifier），公式必须精确表达假设，
   不允许“命名是 A、公式是 B”的错配。

使用建议：
- 先形成自己的经济/微观结构假设、事前符号与 falsifier，再落到下方字段与算子；
- explore 轨应优先尝试与已有 depth/layering/reversal/OB-imbalance 族内容不同
  的方向；失败即冻结该方向，把预算留给更多不同的新机制——系统鼓励广撒网式的
  新颖尝试，而不是在同一条失败族上反复修补；
- 每个提案必须指出它比现有领先因子“多看到了什么信息”（盘口形状、日内波动
  结构、尾盘参与度等），而不是换字段或加负号。
"""

SCORING_METRIC_SPECS = {
    "quick_rank_ic_tstat": "残差化前廉价筛选；配置阈值是最低绝对t值",
    "corr_gate": "候选与任一RefSet成员的平均绝对截面相关上限",
    "spanning_r2_max": "候选被整个RefSet逐日联合回归解释的平均R²上限",
    "spanning_t_min": "候选去除整个RefSet张成部分后，残差RankIC最低t值",
    "pfs_min": "PFS是对因子加入Gaussian和t(3)噪声后的截面排序保真度下限，不是胜率",
    "en_alpha": "滚动Elastic Net的alpha",
    "en_l1_ratio": "滚动Elastic Net的L1比例",
}

SYSTEM_PROMPT = f"""你是 BigAlpha 2026 的因子机制规划 Agent A。
你不是自由写代码的聊天机器人；你的输出会直接约束一个严格类型 DSL。

目标函数：寻找风险残差化后仍有预测力、且不被 RefSet 单因子或组合张成的因子。
最终研究目标是生产具有前沿增量信息的 state-of-the-art 因子。用户报告的平台
实测分数最低目标为 0.85、冲刺目标为 0.90；历史 0.70/0.76 只是当前基线，
不是成功终点。平台分数量纲对本地评分器不透明，只能作为独立后验排序证据，
不得据此伪造本地 IC、t-stat 或任意阈值的数学映射。
纯正交噪声没有价值；纯动量、反转、规模、波动、流动性或简单 OBI 也没有价值。
实际研究数据是 2024 全年 A 股 1 分钟 bar（bigalpha_2026_e2e_bar1m），
已离线聚合成 69 个日频特征（automation/panel/daily_features.py）：
日内已实现波动率、VWAP 偏离、首/尾 30 分钟收益、尾盘量额份额、三档盘口
收盘快照与全天均值/波动、队列陡峭度、档位价差、microprice 溢价等。
因子在日频特征上构造，每个交易日一个横截面，预测下一交易日收盘收益；
目标不是下一根 1m/30m 收益。

{RESEARCH_PRIORS}

{FRONTIER_SUGGESTIONS}

硬规则：
- 每个提案只有一个主要机制假设，并声明提交对象的事前 RankIC 符号。
- 调度器会在同一轮创建多个独立提案；exploit 必须从指定历史因子继续，
  explore 必须提出不依赖历史父因子的正交新方向，两者不可偷换。
- 机制陈述必须先于公式，包含可证伪预测、边界条件和最便宜的消融实验。
- 必须说明它为何可能超越两个传统父机制；不能只说“公式更复杂所以正交”。
- 只能选择下方明确给出的字段、算子和 combine；不得提出时段门控、五档盘口、
  自由 SQL、行业数据或 DSL 无法执行的变换。
- rank 和 zscore 只能出现在 preferred_combines / Genome.combine，绝不是 block op；
  allowed_ops 只能逐字复制“可执行算子及语义”目录中的键。
- 当前语法不是表达式树。一个 block 只能读取原始字段，不能读取另一个 block
  的结果，禁止 ratio(ratio(...), ...) 等嵌套。Genome 等于 1–4 个带正负号
  block；每个 block 先在同一交易日做截面 rank 或 zscore，再等权平均并做
  最终 rank/zscore。因此不同单位可以组合，但不得声称原始数值“同一尺度”。
- 风险残差化由统一评分器完成；不得建议把本地回归残差本身作为提交公式。
- exploit 要提炼平台领先父因子的有效组成，但不能只做窗口微调或同义改写；
  explore 要主动寻找可能越过 0.85 目标、且与领先父因子内容正交的新机制。
- `leader_factor_sequence` 是跨轮长期保留的少量领先因子。优先学习其机制与有效
  组成，同时把 `evidence_scope=local_unconfirmed` 与平台验证严格区分；普通失败
  不进入长期序列，只服从上一轮 Summarizer 的失败反馈。
- 当 diagnostics.combination_mode=single_factor_mining 时，本轮只挖单因子机制，
  不得提出跨历史因子的动态轮动或组合公式。combination_guardrails
  只用于避免破坏性合成，并保留有状态互补潜力的机制多样性；不改变本轮任务。
- 不得读取或建议触碰 2025；当前自动研究只使用配置声明的 2024 窗口。
- 输出一个 JSON 对象，不得附加解释文字。
"""


TEMPLATE_SCHEMA: dict[str, Any] = {
    "research_track": "exploit 或 explore",
    "parent_factor_ids": ["exploit 必须引用给定历史 factor_id；explore 必须为空"],
    "hypothesis": "机制先行的一句话假设",
    "ex_ante_sign": "+ 或 -",
    "proposal_type": "new_mechanism 或 repair",
    "parent_mechanisms": ["传统机制A", "传统机制B"],
    "incremental_mechanism": "为何交互后可能超越两个父机制",
    "falsifier": "什么观测会否定机制，而非仅仅分数较低",
    "transfer_caveat": "研究先验迁移到A股1m日频特征盘口时的限制",
    "search_space": {
        "allowed_ops": ["严格从允许列表选择"],
        "allowed_fields": ["严格从实际字段选择"],
        "preferred_combines": ["zscore 或 rank"],
        "block_count": [1, 3],
    },
    "prototype_genome": {
        "combine": "rank",
        "blocks": [
            {"op": "ratio", "inputs": ["原始字段A", "原始字段B"],
             "params": {}, "sign": "+"},
            {"op": "ratio", "inputs": ["原始字段C", "原始字段D"],
             "params": {}, "sign": "-"},
        ],
    },
    "variant_genomes": [
        {
            "combine": "rank",
            "blocks": [
                {"op": "raw", "inputs": ["原始字段A"],
                 "params": {}, "sign": "+"},
            ],
        },
    ],
    "ablation_plan": [
        {"test": "单独父机制/去掉一条腿", "expected": "若机制成立应看到什么"},
    ],
    "orthogonality_plan": {
        "nearest_baselines": ["预计最接近的 RefSet/本地经典风格"],
        "why_not_spanned": "为何可能保留联合回归残差",
    },
    "kill_criteria": [
        "使用已有评分字段写明确条件，不编造阈值",
    ],
    "search_directions": [
        {"direction": "DSL内可执行的单一变化", "priority": 1,
         "rationale": "与机制和失败证据的关系"},
    ],
}


def _memory_block(memory_path: Path) -> str:
    if memory_path.exists():
        return memory_path.read_text(encoding="utf-8")[-8000:]
    return "（干净记忆，尚无已验证轮次）"


def _build_prompt(
    memory_path: Path,
    round_no: int,
    diagnostics: dict[str, Any],
    available_fields: tuple[str, ...],
    scoring_context: dict[str, Any] | None = None,
    research_track: str = "explore",
    parent_candidates: list[dict[str, Any]] | None = None,
    mechanism_slot: int = 1,
) -> list[dict[str, str]]:
    field_catalog = {
        field: FIELD_DESCRIPTIONS[field] for field in available_fields
        if field in FIELD_DESCRIPTIONS
    }
    op_catalog = {
        op: OPERATOR_SPECS[op] for op in SUPPORTED_OPS if op in OPERATOR_SPECS
    }
    if research_track not in {"exploit", "explore"}:
        raise ValueError(f"非法 research_track: {research_track}")
    track_instruction = (
        "这是延续轨：必须从下方候选父因子中选择至少一个 parent_factor_ids，"
        "proposal_type 必须为 repair，并围绕其已观察优势做机制内深化；不能改写成全新方向。"
        if research_track == "exploit" else
        "这是探索轨：parent_factor_ids 必须为空，proposal_type 必须为 new_mechanism；"
        "应避开 archive 中已有机制与高信用 motif 的简单重组，提出内容上更正交的新方向。"
    )
    user = f"""轮次：{round_no}；本轮机制槽位：{mechanism_slot}；轨道：{research_track}

轨道硬约束：
{track_instruction}

允许引用的历史父因子（含真实 genome 与指标；explore 只用于避重）：
{json.dumps(parent_candidates or [], ensure_ascii=False, indent=2)}

可信长期记忆（旧 planner.md 已因错误数据/schema 被隔离，不在这里）：
{_memory_block(memory_path)}

上一轮机器证据与 Agent B 建议：
{json.dumps(diagnostics, ensure_ascii=False, indent=2)}

本轮评分器真实配置（kill criteria 只能引用这里的值）：
{json.dumps(scoring_context or {}, ensure_ascii=False, indent=2)}

评分指标语义：
{json.dumps(SCORING_METRIC_SPECS, ensure_ascii=False, indent=2)}

实际字段目录：
{json.dumps(field_catalog, ensure_ascii=False, indent=2)}

可执行算子及语义：
{json.dumps(op_catalog, ensure_ascii=False, indent=2)}

可用 combine：{list(COMBINE_OPS)}

输出 schema：
{json.dumps(TEMPLATE_SCHEMA, ensure_ascii=False, indent=2)}

prototype_genome 与每个 variant_genomes 都必须是当前非嵌套 DSL 可直接执行的
完整 Genome，不能写伪代码；所有自然语言 search_directions 必须至少对应其中
一个可执行 variant，禁止提到 search_space 外的字段或算子。
先在内部检查：字段存在、算子 arity 可满足、假设只有一个、符号属于日频 T+1
提交对象、消融能区分交互机制与父机制、正交性陈述是待检验预测而不是既成事实。
只返回 JSON。
"""
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def validate_template(template: dict[str, Any],
                      available_fields: tuple[str, ...], *,
                      expected_track: str | None = None,
                      allowed_parent_ids: set[str] | None = None) -> None:
    required = set(TEMPLATE_SCHEMA)
    missing = sorted(required.difference(template))
    if missing:
        raise ValueError(f"planner 输出缺字段: {missing}")
    if template["ex_ante_sign"] not in {"+", "-"}:
        raise ValueError("planner ex_ante_sign 必须是 + 或 -")
    if template["proposal_type"] not in {"new_mechanism", "repair"}:
        raise ValueError("planner proposal_type 非法")
    track = template["research_track"]
    if track not in {"exploit", "explore"}:
        raise ValueError("planner research_track 非法")
    if expected_track is not None and track != expected_track:
        raise ValueError(
            f"planner 返回轨道 {track}，但调度器要求 {expected_track}")
    parent_ids = template["parent_factor_ids"]
    if not isinstance(parent_ids, list) or any(
            not isinstance(value, str) or not value for value in parent_ids):
        raise ValueError("planner parent_factor_ids 必须是字符串列表")
    if track == "exploit":
        if template["proposal_type"] != "repair" or not parent_ids:
            raise ValueError("exploit 必须是 repair 且至少引用一个历史父因子")
        unknown = sorted(set(parent_ids).difference(allowed_parent_ids or set()))
        if unknown:
            raise ValueError(f"exploit 引用了未授权父因子: {unknown}")
    elif parent_ids or template["proposal_type"] != "new_mechanism":
        raise ValueError("explore 必须是 new_mechanism 且 parent_factor_ids 为空")
    parents = template["parent_mechanisms"]
    if not isinstance(parents, list) or len(parents) != 2:
        raise ValueError("planner 必须声明两个 parent_mechanisms")
    if not isinstance(template["ablation_plan"], list) or not template["ablation_plan"]:
        raise ValueError("planner 必须提供消融计划")
    if not isinstance(template["search_directions"], list) or not template["search_directions"]:
        raise ValueError("planner 必须提供 DSL 内搜索方向")
    space = template["search_space"]
    variants = template["variant_genomes"]
    if not isinstance(variants, list) or not variants:
        raise ValueError("planner 必须提供至少一个 variant_genome")
    for label, raw_genome in [
        ("prototype", template["prototype_genome"]),
        *[(f"variant[{index}]", value) for index, value in enumerate(variants)],
    ]:
        genome = Genome.from_dict(raw_genome)
        errors = validate_genome(genome)
        if errors:
            raise ValueError(f"planner {label} 不可执行: " + "; ".join(errors))
        if genome.combine not in space["preferred_combines"]:
            raise ValueError(f"{label} combine 不在 search_space: {genome.combine}")
        lo, hi = space["block_count"]
        if not lo <= len(genome.blocks) <= hi:
            raise ValueError(f"{label} block数量不在 search_space")
        for block in genome.blocks:
            if block.op not in space["allowed_ops"]:
                raise ValueError(f"{label} op 不在 search_space: {block.op}")
            missing_fields = sorted(set(block.inputs).difference(available_fields))
            if missing_fields:
                raise ValueError(f"{label} 使用不存在字段: {missing_fields}")
            outside = sorted(set(block.inputs).difference(space["allowed_fields"]))
            if outside:
                raise ValueError(f"{label} 字段不在 search_space: {outside}")


class PlannerAgent:
    def __init__(self, client: LLMClient, memory_path: Path | str,
                 scoring_context: dict[str, Any] | None = None) -> None:
        self.client = client
        self.memory_path = Path(memory_path)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.scoring_context = dict(scoring_context or {})

    def plan(
        self,
        round_no: int,
        diagnostics: dict[str, Any],
        *,
        save_memory: bool = True,
        available_fields: tuple[str, ...] | None = None,
        research_track: str = "explore",
        parent_candidates: list[dict[str, Any]] | None = None,
        mechanism_slot: int = 1,
    ) -> dict[str, Any]:
        fields = tuple(available_fields or RAW_FIELDS)
        messages = _build_prompt(
            self.memory_path, round_no, diagnostics, fields,
            self.scoring_context, research_track,
            parent_candidates, mechanism_slot,
        )
        template: dict[str, Any] = {}
        for validation_attempt in range(2):
            template = self.client.chat_json(
                messages, temperature=0.5 if validation_attempt == 0 else 0.1)
            try:
                template["search_space"] = normalize_search_space(template)
                validate_template(
                    template,
                    fields,
                    expected_track=research_track,
                    allowed_parent_ids={
                        str(item["factor_id"]) for item in (parent_candidates or [])
                        if item.get("factor_id")
                    },
                )
                break
            except (KeyError, TypeError, ValueError) as exc:
                if validation_attempt == 1:
                    raise ValueError(
                        f"planner 模板两次未通过严格校验: {exc}") from exc
                messages = [
                    *messages,
                    {"role": "assistant", "content": json.dumps(
                        template, ensure_ascii=False)},
                    {"role": "user", "content": (
                        "上一个 JSON 未通过严格校验：" + str(exc) +
                        "。保持同一个研究机制、事前符号和轨道不变，仅修正 schema/DSL "
                        "错误；不得删除约束、替换父因子或改成更简单的后备方案。"
                        "重新输出完整 JSON 对象。")},
                ]
        if save_memory:
            self._remember(round_no, mechanism_slot, template)
        return template

    def plan_batch(
        self,
        round_no: int,
        diagnostics: dict[str, Any],
        *,
        mechanisms: int,
        available_fields: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        if mechanisms not in {2, 4}:
            raise ValueError("mechanisms_per_round 只能是 2 或 4")
        parents = list(diagnostics.get("archive_elites") or [])
        if parents:
            tracks = ["exploit"] * (mechanisms // 2) + ["explore"] * (mechanisms // 2)
        elif round_no == 1:
            # A fresh first round has no logically possible parent.  This is the
            # explicit bootstrap state; every later round must have persisted evidence.
            tracks = ["explore"] * mechanisms
        else:
            raise RuntimeError("第 2 轮以后缺少 archive_elites，无法执行延续轨")
        templates = []
        for slot, track in enumerate(tracks, start=1):
            # Rotate the primary parent so two exploit slots do not automatically
            # collapse onto the same family.  The single-item allow-list makes the
            # assignment enforceable rather than merely a prompt suggestion.
            if track == "exploit":
                offset = (slot - 1) % len(parents)
                parent_candidates = [parents[offset]]
            else:
                parent_candidates = parents
            templates.append(self.plan(
                round_no,
                diagnostics,
                save_memory=False,
                available_fields=available_fields,
                research_track=track,
                parent_candidates=parent_candidates,
                mechanism_slot=slot,
            ))
        hypotheses = [
            " ".join(str(template["hypothesis"]).lower().split())
            for template in templates
        ]
        if len(hypotheses) != len(set(hypotheses)):
            raise ValueError("同一轮 planner 返回了重复机制；严格模式拒绝合并搜索族")
        prototype_ids = [
            Genome.from_dict(template["prototype_genome"]).fingerprint()
            for template in templates
        ]
        if len(prototype_ids) != len(set(prototype_ids)):
            raise ValueError("同一轮 planner 返回了重复 prototype；严格模式拒绝机制重叠")
        # Batch validation is transactional: a failed/duplicate batch must not
        # contaminate long-term memory with only its early slots.
        for slot, template in enumerate(templates, start=1):
            self._remember(round_no, slot, template)
        return templates

    def _remember(self, round_no: int, mechanism_slot: int,
                  template: dict[str, Any]) -> None:
        entry = (
            f"\n## Round {round_no} / mechanism {mechanism_slot}\n"
            f"- research_track: {template['research_track']}\n"
            f"- parent_factor_ids: {json.dumps(template['parent_factor_ids'], ensure_ascii=False)}\n"
            f"- hypothesis: {template['hypothesis']}\n"
            f"- ex_ante_sign: {template['ex_ante_sign']}\n"
            f"- proposal_type: {template['proposal_type']}\n"
            f"- parents: {json.dumps(template['parent_mechanisms'], ensure_ascii=False)}\n"
            f"- falsifier: {template['falsifier']}\n"
        )
        with self.memory_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)


def make_planner(config: dict, client: LLMClient) -> PlannerAgent:
    return PlannerAgent(client, config["llm"]["memory"]["planner"],
                        config.get("evaluate"))
