# Summarizer v2 trusted memory

Only evidence from the validated 2023 30m cache, explicit risk residualization,
and non-empty RefSet may be appended below.

## Verified round memory
2023 30m 本地残差化与 RefSet 校验：报价单笔规模不对称家族中，凡含 order_book_imbalance 的表达式 fitness 虽高，但 max_corr_refset 0.71-0.85，全部被 RefSet 捕获；低相关候选在 conditional spanning 后 residual t<2.0；Elastic Net 中 model_score=1.18（12% percentile）死亡。目前无确认窗证据，keep 只表示训练窗未淘汰。

## Verified round memory
2023 30m本地残差化与RefSet校验：订单簿衰减家族（最后一根30m快照）本轮6例EN死亡、5例条件跨越失败、1例与RefSet高相关(0.74)、2例快速筛t<1.5；仅2例(c610a0ff13cf0380、a067fcebd57345dc)在训练窗保留，但split=train且无确认窗证据，不得视为OOS通过。该家族多数显著RankIC不构成增量，应冻结新增变体并等待独立确认窗结果。

## Verified round memory
2023 30m 本地残差化与 RefSet 校验：报价单笔规模不对称 repair 家族 5 例（876b4688f65a4429、9e35a0322d8d1dc8、4a6bf508d51d45e2、bd6827cd111e03c4、68548f94b3d7595d）在训练窗为 keep_unconfirmed，max_corr_refset 0.138-0.443，neutralized t 12.1-20.9，但 split=train 且无确认窗，不得视为 OOS 通过。探索家族中 order_book_imbalance 主导的 crowded_duplicate（7bed3a6f965edfde、a9ecf8fd558e4657）corr 0.6885/0.7114 被 RefSet 吸收；卖方一二档委托笔数陡峭度家族 ee0e985d467059dc 在 conditional spanning 后 residual t=1.98 被判定 spanned_by_pool；同家族 4353a92611aa8ca8、85a184ef758ef2c3 符号与事前相反且 model_score 低，列为 wrong_sign_candidate，未确认前不得翻转。

## Verified round memory
第4轮（2023 30m本地残差化）10个keep_unconfirmed，全部split=train无确认窗；0bdead、2bd1、b719等max_corr_refset为0.1947/0.5011/0.4998，neutralized t 12.1-12.9，但不可视为OOS。b719单腿不匹配假说，90ef与5c89表达式等价重复，判contract_error/crowded_duplicate；后续先做基因型-假说一致性校验，再进独立确认窗。

## Verified round memory
第5轮：5个 repair 候选（a69b、d34a、2c3a、1ffe、5857）在训练窗为 keep_unconfirmed，max_corr_refset 0.30-0.53，neutralized t 12.1-20.9，model_score 4.9-10.7，但 split=train 且无确认窗，不得视为 OOS。探索家族 4 例因 max_corr_refset>=0.61 被 RefSet 吸收，1例（4b24819f）条件跨越后残差 t=1.47 被判 spanned_by_pool；显著 RankIC 不构成增量。下一步先做独立确认窗与基因型-假说一致性校验，再决定是否提升。

## Verified round memory
第6轮（2023 30m 本地残差化+RefSet）：5 个 keep_unconfirmed（6567928adbc41ba5、9795480c536082f1、3ddf33b094a111e9、89004d6bac405237、4219d87013f3c0bf）全部为 split=train 无确认窗，不得视为 OOS；卖方单笔笔数虚增家族（e3b3/2c44）与尾盘吸收家族（4c96/b04）均为 ex_ante=-/observed=+ 的 wrong_sign_candidate，dfcd 另因 model_score=1.23 判 EN 死亡；这些候选未确认前不得翻转符号。下一步以独立确认窗为唯一提升门槛。

## Verified round memory
2024-01-01..2024-12-31本地残差化+非空RefSet：8例keep_unconfirmed（994bb252eb79cac9、72a21419b1070050、091c5708c258472d、6a11ea82f71c8620、9647dc622510fbba、bdde77a7b29e763d、1ba8eddc46ad22dc、5e0339cb696dab6e）均split=train，无独立确认窗，不得视为OOS；2例spanned_by_pool（85a184ef758ef2c3、1969bac35bd114fe）residual t=0.55/0.13，显著RankIC不构成增量。本轮无新wrong_sign_candidate；85a184ef758ef2c3旧wrong_sign标签被本轮+/+与spanned_by_pool覆盖。下一步唯一提升门槛是独立确认窗+基因型-假说一致性校验。

## Verified round memory
2024-01-01..2024-12-31本地残差化+非空RefSet第2轮：9de/011两个85A184EF repair被RefSet张成（corr 0.51-0.52，条件跨越残差t<0.4）；c2c保留但split=train无确认窗，且基因型(-ask_num_orders1)与假说不匹配。5857家族2例contract_error；三档盘口疏密家族3例signal_weak；早盘集中度家族2例wrong_sign_candidate且确认窗失败。本轮无任何OOS通过。下一步唯一门槛是独立确认窗+基因型-假说一致性校验。
