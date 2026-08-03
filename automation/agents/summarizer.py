"""Agent B: evidence-bound reflection and next-round advice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm_client import LLMClient


METRIC_GLOSSARY = {
    "neutralized_rank_ic": "本地风险残差化后的日频RankIC均值",
    "neutralized_rank_ic_ir": "本地风险残差化后的RankIC均值/时间序列标准差",
    "neutralized_rank_ic_tstat": "本地风险残差化后RankIC的时间序列t值",
    "pfs": "本地Perturbation Fidelity Score：加入Gaussian与t(3)噪声后的截面排序保真度",
    "ls_sharpe": "本地因子分组多空收益Sharpe",
    "max_corr_refset": "本地候选与RefSet成员的最大平均绝对截面相关",
    "model_score": "本地滚动Elastic Net rehearsal的权重稳定性代理，不是官方B分",
    "kept_fraction": "本地滚动Elastic Net窗口中候选权重非零的比例",
}


SYSTEM_PROMPT = """你是 BigAlpha 2026 的实验审计与反思 Agent B。
你只能依据输入记录中的字段下结论，不得补写不存在的窗口、频率、档位、RefSet
或平台分数。每个结论必须引用 factor_id 和 metric path。
除非记录明确 split=platform 且含官方结果来源，否则所有 metrics 都是本地指标；
尤其不得把 PFS、model_score、kept_fraction 或 ls_sharpe 称为平台分数、官方分数
或 leaderboard 结果。

研究边界：
- Liu et al. 的 failure-inversion 64% 是美国年度会计因子的标签统计，不是本项目
  裸加负号的成功率。wrong-sign 只有在事前符号相反且残差化后的统计证据足够时
  才值得形成一个“新机制 repair”；不得建议只乘以 -1，不得同时保留正反版本。
- Liu et al. 的核心警告是 subsumption：显著不等于增量；优先解释 corr gate、
  spanning 和 Elastic Net 死亡。
- Huatai 的核心警告是发现窗改善只有部分传到测试窗；没有确认窗证据时必须明确
  写“未确认”，不能写“稳健”或“OOS通过”。
- 项目目标是“前沿、崭新的尝试”，鼓励每一轮探索更多不同的新方向：一个探索族
  一旦失败（verdict=retire）即冻结该方向，不建议在同族内继续 repair、换参数
  或重复微调；把预算留给更多不同的新机制。只有明确 keep 或平台验证过的方向
  才允许 continue/repair。冻结时必须写清楚失败归因（哪个 gate、什么证据），
  供后续方向避开同类错误。

分类必须区分：signal_weak、wrong_sign_candidate、crowded_duplicate、
spanned_by_pool、elastic_net_death、contract_error、keep_unconfirmed。
输出严格 JSON，不得附加解释。
"""


SUMMARY_SCHEMA = {
    "round_diagnosis": {
        "dominant_failure": "上述分类之一或 none",
        "evidence": [
            {"factor_id": "id", "metric_path": "metrics.xxx",
             "value": "原值", "interpretation": "不越过证据的解释"},
        ],
        "family_decision": "continue / repair / freeze",
    },
    "wrong_sign_review": [
        {"factor_id": "id", "qualifies": False,
         "reason": "事前符号、残差化证据与规则风险",
         "requires_new_mechanism": True},
    ],
    "lessons": ["可复用且有证据的教训"],
    "next_round_advice": [
        {"action": "给 Planner 的单一可执行动作",
         "evidence_factor_ids": ["id"], "forbidden_shortcut": "不能怎么做"},
    ],
    "updated_memory": "仅写经本轮可信数据验证、未来仍有用的短段落",
}


def _machine_bucket(record: dict[str, Any]) -> str:
    metrics = record.get("metrics", {})
    prep = record.get("preprocessing", {})
    reason = str(record.get("kill_reason") or "")
    if (record.get("stage_reached") == 1
            or str(record.get("kill_reason") or "").startswith("contract")
            or (prep and not prep.get("neutralized"))):
        return "contract_error"
    if metrics.get("max_corr_refset", 0) >= 0.6:
        return "crowded_duplicate"
    if "spanning" in reason:
        return "spanned_by_pool"
    if "Elastic" in reason or "weight held" in reason:
        return "elastic_net_death"
    sign_mismatch = record.get("ex_ante_sign") in {"+", "-"} and (
        record.get("ex_ante_sign") != record.get("sign_observed"))
    tstat = abs(float(metrics.get("neutralized_rank_ic_tstat", 0) or 0))
    if sign_mismatch and tstat >= 1.5:
        return "wrong_sign_candidate"
    if record.get("verdict") == "keep":
        return "keep_unconfirmed"
    return "signal_weak"


def _build_prompt(records: list[dict[str, Any]], memory_path: Path) -> list[dict[str, str]]:
    if not records:
        raise ValueError("summarizer 不接受空记录")
    enriched = [{**record, "machine_bucket": _machine_bucket(record)}
                for record in records]
    memory = (memory_path.read_text(encoding="utf-8")[-8000:]
              if memory_path.exists() else "（干净记忆）")
    user = f"""本轮可信记录（每条已先由程序分类）：
{json.dumps(enriched, ensure_ascii=False, indent=2)}

评分指标词典：
{json.dumps(METRIC_GLOSSARY, ensure_ascii=False, indent=2)}

可信长期记忆（旧 summarizer.md 已因错误数据/空 RefSet 被隔离）：
{memory}

输出 schema：
{json.dumps(SUMMARY_SCHEMA, ensure_ascii=False, indent=2)}

程序分类是下限约束：你可以解释但不能把 crowded_duplicate 改写成新颖因子，
不能把 keep_unconfirmed 写成 OOS 通过。只返回 JSON。
"""
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def validate_summary(summary: dict[str, Any]) -> None:
    missing = sorted(set(SUMMARY_SCHEMA).difference(summary))
    if missing:
        raise ValueError(f"summarizer 输出缺字段: {missing}")
    diagnosis = summary["round_diagnosis"]
    if diagnosis.get("family_decision") not in {"continue", "repair", "freeze"}:
        raise ValueError("summarizer family_decision 非法")
    if not isinstance(diagnosis.get("evidence"), list):
        raise ValueError("summarizer evidence 必须是列表")
    if not isinstance(summary["next_round_advice"], list):
        raise ValueError("summarizer next_round_advice 必须是列表")
    if not isinstance(summary["updated_memory"], str):
        raise ValueError("summarizer updated_memory 必须是字符串")


class SummarizerAgent:
    def __init__(self, client: LLMClient, memory_path: Path | str) -> None:
        self.client = client
        self.memory_path = Path(memory_path)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)

    def summarize(self, records: list[dict[str, Any]], *,
                  save_memory: bool = True) -> dict[str, Any]:
        summary = self.client.chat_json(
            _build_prompt(records, self.memory_path), temperature=0.2)
        validate_summary(summary)
        if save_memory and summary["updated_memory"].strip():
            with self.memory_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n## Verified round memory\n{summary['updated_memory'].strip()}\n")
        return summary


def make_summarizer(config: dict, client: LLMClient) -> SummarizerAgent:
    return SummarizerAgent(client, config["llm"]["memory"]["summarizer"])
