#!/usr/bin/env python3
"""把用户提供的比赛公榜最新快照写入 platform_feedback.json 与 leader_factor_sequence.json。

规则：
- 榜单得分是动态快照；每次观测追加到 prior_reported_scores，reported_score 取最新值。
- tier 只按当前快照的相对分档（leader>=0.60 / middle 0.45-0.60 / laggard<0.45），
  不代表永久结论；confirmed_retire 仅保留给"多次观测均处于垫底"的因子。
- 外部手工因子（close_reverse 等）不在 automation ledger 的 genome 中，
  不能进 platform_feedback.json（严格加载器要求 factor_id 必须可恢复 genome），
  只更新 leader_factor_sequence.json。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "automation/runs/trial_20260802_r3"
FEEDBACK = RUN_DIR / "platform_feedback.json"
LEADER_SEQ = ROOT / "automation/memory/leader_factor_sequence.json"

# notebook 文件名 -> factor_id（与 ledger / upload_receipt 一一对应）
NOTEBOOK_TO_ID = {
    "r5_m2_ask_liquidity_quote_gap_bid3_reversal_1ffe1175": "1ffe11756e87b138",
    "r5_m2_ask_liquidity_quote_gap_bid1_reversal_5857ca18": "5857ca18f26c3a5b",
    "r5_m1_double_depth_count_close_reversal_d34abb17": "d34abb176ff7f5a3",
    "r5_m1_depth_count_close_reversal_a69b942c": "a69b942c66a67150",
    "r5_m1_depth_close_reversal_2c3a2406": "2c3a24064601eeb2",
    "r4_m3_ask_order_layering_depth_fd6a982e": "fd6a982e80806c30",
    "r4_m4_ask_order_layering_ratio_3a657cc7": "3a657cc77740192d",
    "r4_m2_ask_order_layering_unit_size_cb1e859b": "cb1e859b7b3cdb27",
    "r4_m1_sell_pressure_quote_interaction_0bdead70": "0bdead706272a99d",
    "r3_m4_obi_adjustment_price_crowding_a9ecf8fd": "a9ecf8fd558e4657",
    "r3_m3_depth_order_count_structure_85a184ef": "85a184ef758ef2c3",
    "r3_m2_ask_depth_price_range_bd6827cd": "bd6827cd111e03c4",
    "r3_m1_quote_order_depth_interaction_876b4688": "876b4688f65a4429",
    "r2_order_granularity_depth_structure_c610": "c610a0ff13cf0380",
    "r2_low_ask_order_density_vs_biddepth_a067": "a067fcebd57345dc",
    "r1_small_trade_quote_gap_biddepth_c3d5": "c3d5e4996557a64d",
    "r1_low_trade_bidvalue_askorders_d453": "d4531be5a8960e80",
    "r1_low_ask_order_activity_midprice_f397": "f3974be80e474c45",
    "r1_bid_order_persistence_vs_ask_pressure_323a": "323a9cf9a966aa7a",
}

# 新加入 feedback 的 R5 因子显示名
ID_TO_DISPLAY = {
    "1ffe11756e87b138": "R5 M2 ask liquidity quote gap bid3 reversal 1FFE1175",
    "5857ca18f26c3a5b": "R5 M2 ask liquidity quote gap bid1 reversal 5857CA18",
    "d34abb176ff7f5a3": "R5 M1 double depth count close reversal D34ABB17",
    "a69b942c66a67150": "R5 M1 depth count close reversal A69B942C",
    "2c3a24064601eeb2": "R5 M1 depth close reversal 2C3A2406",
}

# 用户 2026-08-03 公榜快照（只包含本次有得分的因子；
# 未出现的因子保持原分数不动，ordinal_rank/tier 仍按全体已得分因子重排）
SNAPSHOT: dict[str, float | None] = {
    "1ffe11756e87b138": 0.40795,
    "5857ca18f26c3a5b": 0.76800,
    "d34abb176ff7f5a3": 0.57608,
    "2c3a24064601eeb2": 0.29293,
    "3a657cc77740192d": 0.73261,
    "cb1e859b7b3cdb27": 0.53239,
    "0bdead706272a99d": 0.30999,
    "85a184ef758ef2c3": 0.80726,
    "bd6827cd111e03c4": 0.59937,
    "876b4688f65a4429": 0.64334,
    "c610a0ff13cf0380": 0.64131,
    "c3d5e4996557a64d": 0.68315,
    "d4531be5a8960e80": 0.78165,
    "f3974be80e474c45": 0.54781,
}

OBSERVED_AT = "2026-08-03"


def tier_for(score: float | None) -> str:
    if score is None:
        return "laggard"
    if score >= 0.60:
        return "leader"
    if score >= 0.45:
        return "middle"
    return "laggard"


def main() -> None:
    feedback = json.loads(FEEDBACK.read_text(encoding="utf-8"))
    by_id = {str(item["factor_id"]): item for item in feedback["factors"]}

    existing_ids = set(by_id)
    for fid, score in SNAPSHOT.items():
        if fid not in existing_ids:
            by_id[fid] = {
                "factor_id": fid,
                "display_name": ID_TO_DISPLAY[fid],
                "prior_reported_scores": [],
                "precision": "unknown",
                "tier": "laggard",
            }
            feedback["factors"].append(by_id[fid])

    for fid, score in SNAPSHOT.items():
        item = by_id.get(fid)
        if item is None:
            raise ValueError(f"snapshot 中出现未知 factor_id: {fid}")
        # 幂等：同一快照已应用过则跳过（避免把当前分数重复追加进历史）
        if (score is not None and item.get("observed_at") == OBSERVED_AT
                and item.get("reported_score") is not None
                and abs(float(item["reported_score"]) - float(score)) < 1e-12):
            continue
        prior = item.get("reported_score")
        history = list(item.get("prior_reported_scores") or [])
        if prior is not None:
            if history and abs(history[-1] - float(prior)) < 1e-12:
                pass
            else:
                history.append(float(prior))
        item["prior_reported_scores"] = history
        if score is not None:
            item["reported_score"] = score
            item["precision"] = "exact"
            item["score_scope"] = "dynamic_leaderboard_snapshot"
            item["observed_at"] = OBSERVED_AT
            item["platform_conclusion"] = (
                f"{OBSERVED_AT} 公榜快照 {score:.5f}；榜单流动，单次快照不构成永久结论"
            )

    # confirmed_retire 只保留给"多次观测都处于垫底"的因子；R4M4(3a657cc7) 新快照
    # 已升至 0.673，属于单次高观测，撤销 retire 并降为保守档位。
    for fid, item in by_id.items():
        history = [float(v) for v in (item.get("prior_reported_scores") or [])]
        latest = item.get("reported_score")
        observations = history + ([float(latest)] if latest is not None else [])
        if item.get("platform_decision") == "confirmed_retire":
            if fid == "3a657cc77740192d":
                item["platform_decision"] = "reobserve"
                item["platform_conclusion"] = (
                    "2026-08-03 公榜 0.67304，显著高于 R4 其余探针；"
                    "撤销此前 confirmed_retire，作为单次高观测重新观察"
                )
            elif len(observations) >= 2 and all(v < 0.45 for v in observations):
                item["platform_conclusion"] = (
                    "多次公榜观测均低于 0.45，维持 confirmed_retire；"
                    "榜单若大幅回升可再解除"
                )
            else:
                item["platform_decision"] = "reobserve"
                item["platform_conclusion"] = (
                    "此前按用户口述标记 retire；2026-08-03 公榜快照已记录，先解除硬淘汰"
                )

    # ordinal_rank / tier 必须在分数全部更新后再重排（基于全体已有数值分数，
    # 不只基于本次快照）。
    scored = [(fid, float(item.get("reported_score")))
              for fid, item in by_id.items()
              if item.get("reported_score") is not None]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    rank_of = {fid: index + 1 for index, (fid, _) in enumerate(scored)}
    for fid, item in by_id.items():
        if item.get("reported_score") is not None:
            item["ordinal_rank"] = rank_of[fid]
            item["tier"] = tier_for(float(item["reported_score"]))

    feedback["updated_at"] = OBSERVED_AT
    FEEDBACK.write_text(
        json.dumps(feedback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- leader_factor_sequence 同步 ----
    seq = json.loads(LEADER_SEQ.read_text(encoding="utf-8"))
    leaders = {str(item["factor_id"]): item for item in seq["leaders"]}
    external_scores = {
        "external_close_reverse_price_amount_momentum_v1": 0.46686,
        "external_intraday_trend_exhaustion_v1": 0.54365,
    }
    for fid, score in external_scores.items():
        item = leaders.get(fid)
        if item is None:
            continue
        item["reported_score"] = score
        item["evidence_scope"] = "platform_leaderboard"
        item["observed_at"] = OBSERVED_AT
    for external_id, display, score in (
        ("external_shape_order_size_v1", "Shape order size v1", 0.49679),
        ("external_lightgbm_severe_regime_defensive_mix_v3", "LightGBM severe regime defensive mix v3", 0.75930),
        ("external_orthogonal_regime_specialist_rotation_v5", "Orthogonal regime specialist rotation v5", 0.50755),
    ):
        if external_id not in leaders:
            seq["leaders"].append({
                "factor_id": external_id,
                "display_name": display,
                "evidence_scope": "platform_leaderboard",
                "priority": "external_reference",
                "reported_score": score,
                "observed_at": OBSERVED_AT,
            })
        else:
            leaders[external_id]["reported_score"] = score
            leaders[external_id]["observed_at"] = OBSERVED_AT
    LEADER_SEQ.write_text(
        json.dumps(seq, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("updated factors:", len(SNAPSHOT))
    for fid, score in sorted(SNAPSHOT.items(), key=lambda p: -(p[1] or 0)):
        item = by_id[fid]
        print(
            f"  {item['tier']:<7} rank={item.get('ordinal_rank')} "
            f"{fid[:8]} score={score} prior={item['prior_reported_scores']} "
            f"decision={item.get('platform_decision')}"
        )


if __name__ == "__main__":
    main()
