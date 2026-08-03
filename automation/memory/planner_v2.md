# Planner v2 trusted memory

Only templates produced after the validated 2023 30m cache and non-empty
risk-control/RefSet pipeline may be appended below.

## Round 1
- hypothesis: 在每交易日最后一根30m，用买一与卖一的挂单量对委托笔数做交叉乘积差构造报价单笔规模不对称；当买侧平均单笔挂单规模大于卖侧时，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)", "传统父机制B：top-of-book order count imbalance (OCI)"]
- falsifier: 若bid腿和ask腿单独作用与组合符号不一致，或者level2/level3深度变体在RefSet残差化后方向不稳定且残差RankIC t低于spanning_t_min=2.0，则报价单笔规模不对称机制被否定，而不仅是分数较低。

## Round 2
- hypothesis: 在每交易日最后一根30m收盘快照上，比较买、卖两侧由一档到二档的挂单量与委托笔数衰减速度：当买侧衰减更慢（bid_volume2/bid_volume1 与 bid_num_orders2/bid_num_orders1 相对更大）而卖侧衰减更快时，代表最优报价之后存在单向被动累积的持续性需求，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：top-of-book order book imbalance (OBI，仅一档挂单量失衡)", "传统父机制B：top-of-book order count imbalance (OCI，仅一档委托笔数失衡)"]
- falsifier: 出现以下任一观测都会否定机制本身，而非仅仅分数较低：(1) bid腿单独（variant_genomes[3]）残差RankIC t<2.0或方向为负，即使四块组合显著——说明不对称分解方向不成立，不得通过翻转符号重提；(2) 组合经RefSet条件spanning后neutralized_rank_ic_tstat<2.0或max_corr_refset≥0.6，说明预测力已被L1基线吸收；(3) 二档→三档变体（variant_genomes[2]）方向反转且自身残差t≥2.0，说明不存在深度持续度这一连续参数，只有一档附近的偶然形态；(4) 买卖两腿单独方向相同，即不对称结构的经济含义不成立。边界条件：机制在标准日频提交对象（每交易日最后一根30m）上定义，不附加时段门控；若L2快照在样本中大量为空或长时间静止，则此机制应退化而非加强。

## Round 3 / mechanism 1
- research_track: exploit
- parent_factor_ids: ["d4531be5a8960e80"]
- hypothesis: 在每交易日最后一根30m快照上，保留父因子已有效的低成交笔数-买一价交互条件，把父因子想表达的报价单笔规模不对称直接改写为二/三档每笔挂单规模之差：买侧 bid_volume/bid_num_orders 取正、卖侧 ask_volume/ask_num_orders 取负；当低成交活跃背景下买侧每笔挂单规模大于卖侧时，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)", "传统父机制B：top-of-book order count imbalance (OCI)"]
- falsifier: 边界条件：机制只在每交易日最后一根30m日频提交对象上定义，不附加时段门控；若L2/L3盘口大量为空或长时间静止，则机制应退化而非增强。否定机制本身而非仅分数较低的观测包括：(1) 买侧腿或卖侧腿单独测试时 neutralized_rank_ic_tstat < 2.0，或方向与 ex_ante_sign 相反且 t >= 2.0；(2) 买卖两侧单独方向相同，即不对称结构不成立；(3) prototype 或 L3-only variant 经 RefSet 条件跨越后残差 RankIC t < 2.0，或 spanning R2 > 0.95，说明增量被 RefSet 张成；(4) 任一 RefSet 成员绝对相关 >= 0.6，说明只是 crowded duplicate；(5) L2-only 与 L3-only 方向反转且 L3-only 自身残差 t >= 2.0，说明不存在深度连续性这一参数。

## Round 3 / mechanism 2
- research_track: exploit
- parent_factor_ids: ["c3d5e4996557a64d"]
- hypothesis: 在每交易日最后一根30m，用买一和卖一各自的挂单量除以委托笔数构造每笔挂单规模，并保留父因子中已被本地证据奖励的报价距离腿与远端买盘增长腿：当买侧平均单笔挂单规模大于卖侧、且收盘价相对卖一价处于下方、买三挂单量在增长时，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，只用一档挂单量失衡", "传统父机制B：top-of-book order count imbalance (OCI)，只用一档委托笔数失衡"]
- falsifier: 出现以下任一观测即否定机制而非分数较低：(1) bid 侧与 ask 侧单笔挂单规模腿单独测试时同号且残差 t 显著；(2) 组合经整个 RefSet 条件跨越后 neutralized_rank_ic_tstat < 2.0；(3) 与 RefSet 中 order_book_imbalance 或 order_count_imbalance 的 max_corr_refset >= 0.6，说明只是重复；(4) 去掉显式规模腿后表现不变且另一条腿负责全部信号，说明报价规模不对称不是边际来源。

## Round 3 / mechanism 3
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，卖方一档到二档委托笔数的相对陡峭程度（ask_num_orders2与ask_num_orders1的差异或比率）对次日收盘收益有负向预测力；该预测力独立于买卖一档的静态委托笔数失衡。
- ex_ante_sign: -
- proposal_type: new_mechanism
- parents: ["传统父机制A：top-of-book order count imbalance (OCI，仅比较买卖一档委托笔数失衡)", "传统父机制B：报价单笔规模不对称（挂单量与委托笔数之比），未利用同一侧不同价位的委托笔数梯度"]
- falsifier: 若单一变体ask_num_orders2-ask_num_orders1在RefSet残差化后neutralized_rank_ic_tstat<2.0且方向为正，或者该变体与order_count_imbalance的相关绝对值>=0.6，则卖方笔数斜率机制被否定，而非仅分数较低。若买卖两侧单独使用的方向相同，也否定不对称机制。

## Round 3 / mechanism 4
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，以买一价除买一挂单量所得每手隐含入场成本压力刻画三档买单的微观拥挤度；同时用卖一价逐日增加率刻画卖一侧报价相对上移的速度。两腿组合表达：买单挂单吸收成本越低而卖侧报价越快上移时，说明此前的乐观需求仍在持续累积，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统机制A：top-of-book order book imbalance (OBI)，只看买一卖一挂单量差", "传统机制B：top-of-book order count imbalance (OCI)，只看买一卖一委托笔数差"]
- falsifier: 以下任一观测都会否定该机制，而不是仅说明分数较低：(1) b1=ratio(bid_price1,bid_volume1)的卖出腿单独变体（variant 2）残差RankIC t<2.0，说明价格每手吸收成本腿没有增量；(2) b2=pct_change(ask_price1)的买入腿单独变体（variant 1）符号在RefSet条件化后由负转正，即卖价上移并不对应正向次日收益；(3) 组合的conditional spanning residual RankIC t<2.0或max_corr_refset≥0.6，即使原始残差RankIC t很高，也说明预测力已被现池吸收；(4) 单腿与组合符号不一致且单腿残差t≥2.0，说明不存在一致机制而只是偶然组合。边界条件：机制只在标准提交对象（每交易日最后一根30m）上定义，不使用时段门控；若bid_volume1或ask_price1长时间为0/缺失，则在样本中退化而非增强。

## Round 4 / mechanism 1
- research_track: exploit
- parent_factor_ids: ["d4531be5a8960e80"]
- hypothesis: 在每交易日最后一根30m快照上，用卖二档委托笔数（ask_num_orders2）与成交笔数（deal_number）的乘积构造卖压活跃度，并保留父因子中已获平台证据的低成交笔数-买一价交互腿，以及父因子已有的卖方一档委托笔数负向腿；当低成交活跃背景下的买侧价值交互为正、卖二档活跃度降低、卖一挂单笔数收缩时，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，只用一档挂单量失衡", "传统父机制B：top-of-book order count imbalance (OCI)，只用一档委托笔数失衡"]
- falsifier: 出现以下任一观测即否定机制，而非仅分数较低：(1) 卖二档活跃度腿单独（variant 1）在 RefSet 条件跨越后 neutralized_rank_ic_tstat < 2.0，或方向与事前设计相反且 t >= 2.0；(2) 原型组合经联合回归条件跨越后 neutralized_rank_ic_tstat < 2.0，或 spanning_r2_max > 0.95，说明增量已被 RefSet 张成；(3) 任一 RefSet 成员（尤其 order_book_imbalance 或 order_count_imbalance）的 max_corr_refset >= 0.6；(4) 去掉父因子已有的一档卖方滚动腿后表现不变，说明新的卖二档活跃度腿没有边际来源。

## Round 4 / mechanism 2
- research_track: exploit
- parent_factor_ids: ["85a184ef758ef2c3"]
- hypothesis: 在每交易日最后一根30m快照上，卖三相对卖一的委托笔数比率高于卖三相对卖一的挂单量比率时，说明卖一上方存在被拆细的限价小单而非等量真实供给；次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，只用一档挂单量失衡", "传统父机制B：top-of-book order count imbalance (OCI)，只用一档委托笔数失衡"]
- falsifier: 以下任一观测都否定机制本身，而不只是分数较低：(1) variant_2（仅卖三/卖一委托笔数斜率腿）经RefSet条件跨越后residual RankIC t < spanning_t_min=2.0，或方向为负且t >=2.0，说明卖侧笔数斜率不是增量来源；(2) variant_3（仅卖三/卖一挂单量斜率腿）经条件跨越后residual RankIC t < 2.0，或方向为正且t >=2.0，说明量斜率对照腿没有独立作用；(3) prototype或任一完整variant的max_corr_refset >= corr_gate=0.6，说明只是RefSet拥挤重复；(4) prototype经整个RefSet条件跨越后residual RankIC t < spanning_t_min=2.0或spanning R2 > spanning_r2_max=0.95，说明增量已被RefSet张成；(5) variant_1（L2版）与prototype（L3版）方向相反且两者残差t >=2.0，说明不存在深度连续性参数；(6) 任一完整genome的pfs < pfs_min=0.6，说明排序保真度不足。

## Round 4 / mechanism 3
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，比较买卖两侧报价阶梯的间距：卖二价相对卖一价的间距更宽、买二价相对买一价的间距更窄时，说明上方卖单供给稀疏而贴近最优买价的承接密集，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，只用一档挂单量失衡", "传统父机制B：top-of-book order count imbalance (OCI)，只用一档委托笔数失衡"]
- falsifier: 以下任一观测都否定机制本身，而非仅分数较低：(1) ask 侧间距腿或 bid 侧间距腿单独经 RefSet 条件跨越后 neutralized_rank_ic_tstat < 2.0；(2) 两腿单独残差方向相同且 |t| >= 2.0，说明不是非对称报价阶梯机制；(3) L3-L2 间距变体相对 L2-L1 原型方向反转且自身残差 |t| >= 2.0，说明不存在深度连续性；(4) 组合经 RefSet 条件跨越后 neutralized_rank_ic_tstat < 2.0，或 max_corr_refset >= 0.6，或 spanning_r2 > 0.95，说明信息已被池中基准确吸收。边界条件：机制只在标准日频提交对象（每交易日最后一根30m）上定义，不附加时段门控；若三档价格长期相等或深度为空，机制应退化而非增强。

## Round 4 / mechanism 4
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，比较最高价相对卖三价的超出幅度与最低价相对买三价的超出幅度：当向下穿透（low 低于 bid_price3）明显大于向上穿透（high 高于 ask_price3）时，说明价格已突破可见盘口下边界，卖压被过度消耗而买方承接在后，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，仅用买一/卖一挂单量的静态失衡预测次日收益", "传统父机制B：top-of-book order count imbalance (OCI)，仅用买一/卖一委托笔数的静态失衡预测次日收益"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) 上行穿透腿（difference(high, ask_price3) 取负）与下行穿透腿（difference(bid_price3, low) 取正）单独测试时方向与事前符号相反且残差 t≥2.0，或两者单独方向相同，说明不对称方向不成立；(2) 组合经整个 RefSet 条件跨越后 spanning residual rankIC t<2.0 或 spanning R2>0.95，说明预测力落在 RefSet 张成空间内；(3) 与任一 RefSet 成员 max_corr_refset≥0.6，说明只是 crowded duplicate；(4) PFS<0.6，排序保真度不足；(5) ratio 标准化变体与 difference 变体符号不一致且都经过残差 t≥2.0，说明穿透方向依赖单位而非机制。边界条件：机制只在每交易日最后一根30m日频提交对象上定义，不附加时段门控；若 ask_price3/bid_price3 长时间缺失或静态不变，则机制应退化而非增强。

## Round 5 / mechanism 1
- research_track: exploit
- parent_factor_ids: ["85a184ef758ef2c3"]
- hypothesis: 在每交易日最后一根30m快照上，父因子85的领先信息不应归因于一档OBI/OCI总量，而应归因于委托笔数在盘口深度上的不对称：买二/卖二笔数失衡占优、卖三笔数相对买一笔数更密集、同时买三挂单量相对卖一挂单量仍占优时，代表被动买单在深度上累积且卖方远端被拆细，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)", "传统父机制B：top-of-book order count imbalance (OCI)"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) 仅笔数结构腿（variant_2）经RefSet条件跨越后残差RankIC t<2.0，或方向与ex_ante_sign相反且|t|>=2.0，说明不是买卖两侧笔数深度结构，而是其他腿的附带信号；(2) prototype经整个RefSet联合回归条件跨越后残差RankIC t<2.0，或spanning R2>0.95，说明增量已被RefSet张成；(3) 任一RefSet成员与prototype的max_corr_refset>=0.6，说明只是拥挤重复；(4) variant_3（二档深度版）与prototype方向相反且两者残差|t|>=2.0，说明不存在深度连续性参数；(5) pfs<0.6，说明排序保真度不足。

## Round 5 / mechanism 2
- research_track: exploit
- parent_factor_ids: ["c3d5e4996557a64d"]
- hypothesis: 在每交易日最后一根30m，把父因子用成交均额近似表达的单笔规模不对称，直接改写为同一时点报价侧的单笔挂单规模腿：bid_volume1/bid_num_orders1 取正、ask_volume1/ask_num_orders1 取负，并保留父因子已获平台证据的收盘价低于卖一价的报价缺口腿与买三挂单量增长腿；当买侧每笔挂单规模大于卖侧、收盘价仍处于卖一价下方、且远端买盘在增长时，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，只用一档挂单量失衡", "传统父机制B：top-of-book order count imbalance (OCI)，只用一档委托笔数失衡"]
- falsifier: 以下任一观测都否定机制本身，而不只是分数较低：(1) bid侧单笔挂单规模腿单独或ask侧单笔挂单规模腿单独经RefSet条件跨越后residual rankIC t < spanning_t_min=2.0，或方向与事前设计相反且|t|>=2.0；(2) prototype经整个RefSet条件跨越后residual rankIC t < spanning_t_min=2.0，或spanning R2 > spanning_r2_max=0.95，或max_corr_refset >= corr_gate=0.6，说明预测力已被RefSet张成或只是crowded duplicate；(3) 将prototype中的ask侧规模腿删除后，剩余组合的spanning residual rankIC t不下降且仍>=2.0，说明显式卖侧单笔规模腿没有边际来源；(4) 任一完整genome的pfs < pfs_min=0.6，排序保真度不足；(5) bid_num_orders1或ask_num_orders1在样本中大量为0/缺失时机制应退化而非增强。

## Round 5 / mechanism 3
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，以成交笔数作为成交活跃度条件，构造单位成交对应的残余盘口深度：当卖侧残余挂单量相对成交笔数越厚、而买侧残余挂单量相对成交笔数越薄时，卖压未被成交消耗，次日收盘收益倾向为负；反之倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，仅用买一/卖一挂单量的静态失衡预测次日收益，不除以成交笔数", "传统父机制B：average trade size (amount/deal_number)，刻画已执行成交的平均块头，但忽略成交后的残余挂单深度"]
- falsifier: 以下任一观测都会否定该机制本身，而不是仅说明分数较低：(1) bid-depth-per-trade腿与ask-depth-per-trade腿单独残差方向相同且|neutralized_rank_ic_tstat|>=2.0，说明不是不对称消化而只是流动性或成交规模代理；(2) ratio(ask_volume1, deal_number)与ratio(bid_volume1, deal_number)单独测试时方向分别与事前相反且残差t>=2.0；(3) prototype经整个RefSet条件跨越后neutralized_rank_ic_tstat<spanning_t_min=2.0，或spanning_r2>spanning_r2_max=0.95，或max_corr_refset>=corr_gate=0.6；(4) pfs<pfs_min=0.6；(5) L2/L3深度变体相对L1原型方向反转且自身残差|t|>=2.0，说明机制不具深度连续性。

## Round 5 / mechanism 4
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，若成交量相对卖一挂单量高、同一根收涨并收在接近最高价，说明尾盘主动买盘已耗尽可见卖方流动性并把价格推到高位，次日收盘收益倾向为负。
- ex_ante_sign: -
- proposal_type: new_mechanism
- parents: ["传统父机制A：尾盘价格-成交额动量（close_reverse_price_amount_momentum），只利用价格移动与成交额加权", "传统父机制B：top-of-book order book imbalance (OBI)，只利用买一/卖一挂单量静态失衡"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) ratio(volume, ask_volume1) 或 ratio(close, open) 单独经RefSet条件跨越后 neutralized_rank_ic_tstat<2.0，或方向与事前符号相反且|t|>=2.0；(2) 去掉位置腿 difference(high, close) 后表现不变，说明close位置没有边际作用；(3) prototype经整个RefSet联合回归后 neutralized_rank_ic_tstat<2.0 或 spanning R2>0.95；(4) max_corr_refset>=0.6；(5) PFS<0.6。

## Round 6 / mechanism 1
- research_track: exploit
- parent_factor_ids: ["85a184ef758ef2c3"]
- hypothesis: 在每交易日最后一根30m快照上，把父因子已表达的卖方委托笔数深度结构显式分解为同侧一档到二档的笔数坡度与挂单量坡度：当卖二相对卖一的委托笔数更陡、而卖二相对卖一的挂单量更不陡（即卖一上方出现'笔数虚增但量不实'的拆细卖单）时，该虚假卖方压力在次日倾向于反转，次日收盘收益为负。
- ex_ante_sign: -
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order count imbalance (OCI)，只比较买一/卖一委托笔数，不利用同一侧不同价位笔数梯度", "传统父机制B：top-of-book order book imbalance (OBI)，只比较买一/卖一挂单量，不区分挂单量背后的委托笔数分布"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) 笔数坡度单腿(variant 1)经整个RefSet条件跨越后残差RankIC t < spanning_t_min=2.0，或方向与ex_ante_sign相反且|t|>=2.0；(2) 量坡度单腿(variant 2)经条件跨越后残差RankIC t < 2.0，或方向与ex_ante_sign相反且|t|>=2.0；(3) prototype经整个RefSet联合回归条件跨越后残差RankIC t < 2.0，或spanning R2 > spanning_r2_max=0.95，说明增量已被RefSet张成；(4) 任一RefSet成员与prototype的max_corr_refset >= corr_gate=0.6，说明只是crowded duplicate；(5) variant 3（L3版）与prototype（L2版）方向相反且两者残差|t|>=2.0，说明不存在深度连续性；(6) 任一完整genome的pfs < pfs_min=0.6，排序保真度不足。

## Round 6 / mechanism 2
- research_track: exploit
- parent_factor_ids: ["c3d5e4996557a64d"]
- hypothesis: 在每交易日最后一根30m，把父因子 c3d5 的成交均额代理深化为报价侧跨深度单笔挂单规模不对称：买三每笔挂单规模（bid_volume3/bid_num_orders3）相对卖一每笔挂单规模（ask_volume1/ask_num_orders1）越大，且买三挂单量仍在增长时，代表被动买盘以更大限价单在远端累积而卖方一档被拆细，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，仅用买一/卖一挂单量失衡", "传统父机制B：top-of-book order count imbalance (OCI)，仅用买一/卖一委托笔数失衡"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) variant_1（仅买三每笔挂单规模腿）与 variant_2（仅卖一每笔挂单规模腿）单独经 RefSet 条件跨越后 residual rankIC t 方向相同且 |t| >= 2.0，说明不是买卖不对称而只是单侧流动性代理；(2) prototype 经整个 RefSet 条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或 spanning R2 > spanning_r2_max=0.95，说明预测力已被 RefSet 张成；(3) prototype 或任一完整 variant 的 max_corr_refset >= corr_gate=0.6，说明只是拥挤重复；(4) variant_3（L2/L2 深度版）与 prototype 方向相反且残差 |t| >= 2.0，说明不存在深度连续性参数；(5) 任一完整 genome 的 pfs < pfs_min=0.6，说明排序保真度不足。

## Round 6 / mechanism 3
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，用买一价与卖一价的一阶差分之差（Δbid_price1 - Δask_price1）刻画报价价差变化方向；当买价相对卖价上升、即报价价差收窄时，说明限价单提交方正在边际改善买侧报价，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：静态 top-of-book spread / order_book_imbalance，只用当前时点买卖价差或一档挂单失衡", "传统父机制B：执行价格动量/反转（close_reverse_price_amount_momentum / return(close)），只利用已成交价格路径"]
- falsifier: 以下任一观测都否定该机制本身，而不是仅说明分数较低：(1) bid腿单独与ask腿单独经RefSet条件跨越后方向相同且|neutralized_rank_ic_tstat|>=2.0，说明不是相对报价变化而只是共同报价动量；(2) 原型或任一完整variant经整个RefSet条件跨越后neutralized_rank_ic_tstat<spanning_t_min=2.0，或spanning_r2>spanning_r2_max=0.95，或max_corr_refset>=corr_gate=0.6，说明增量已被RefSet张成或只是crowded duplicate；(3) window=1与window=2的变体方向相反且两者残差|t|>=2.0，说明不存在时间尺度一致性；(4) pfs<pfs_min=0.6，说明排序保真度不足。

## Round 6 / mechanism 4
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，成交量较上一根明显放大、收盘价位于该30m bar上沿、且收盘价未穿越卖一价时，说明尾盘主动买盘以高成本吸收卖方流动性但未能把价格推过可见卖单，透支次日买需，次日收盘收益倾向为负。
- ex_ante_sign: -
- proposal_type: new_mechanism
- parents: ["传统父机制A：close_reverse_price_amount_momentum_v1，用尾盘高成交额的价格推动构造次日的反转信号，但依赖分钟级收益和成交额加权，不使用30m bar内成交量相对前一期的放大，也不使用收盘位置。", "传统父机制B：top-of-book order book imbalance (OBI)，只用买一/卖一挂单量的静态失衡预测次日收益，不包含本根30m bar的成交量变化、bar内收盘位置或收盘价相对卖一价的未穿越状态。"]
- falsifier: 以下任一观测都会否定该机制，而不是仅说明分数较低：(1) 完整prototype经整个RefSet条件跨越后 neutralized_rank_ic_tstat < 2.0 或 spanning_r2 > 0.95，说明预测力已被RefSet张成；(2) 任一完整genome与任一RefSet单因子的 max_corr_refset >= 0.6，说明只是拥挤重复；(3) 删除 quote headroom 腿后的变体条件跨越残差t不下降且仍>=2.0，说明第三条腿没有边际贡献；(4) pct_change(volume) 与 pct_change(amount) 两种口径对应变体方向相反且各自 |t|>=2.0，说明机制依赖测量单位而非微观结构；(5) 任一完整genome的 pfs < 0.6，排序保真度不足。

## Round 1 / mechanism 1
- research_track: exploit
- parent_factor_ids: ["85a184ef758ef2c3"]
- hypothesis: 在每交易日最后一根30m快照上，父因子85A184EF的领先信息不是一档OBI/OCI的静态总量，而是卖方同侧两档的'笔数坡度-量坡度'背离：当卖二相对卖一的委托笔数比率上升、而挂单量比率未同步上升时，卖一上方堆积的是笔数虚增但量不实的拆细卖单而非等量真实供给；在买三挂单量相对卖一挂单量仍占优、且一档委托笔数失衡偏买的状态下，该虚假卖方压力在次日反转向上，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，仅用买一/卖一挂单量的静态失衡预测次日收益", "传统父机制B：top-of-book order count imbalance (OCI)，仅用买一/卖一委托笔数的静态失衡预测次日收益"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) prototype经整个RefSet条件跨越后残差RankIC t < spanning_t_min=2.0，或spanning R2 > spanning_r2_max=0.95，说明增量已被RefSet张成；(2) prototype与任一RefSet单因子max_corr_refset >= corr_gate=0.6，说明只是拥挤重复；(3) 笔数坡度腿ratio(ask_num_orders2, ask_num_orders1)单独经条件跨越后方向与ex_ante_sign相反且|t|>=2.0，说明拆细卖单反转假设的方向不成立；(4) 去掉量坡度腿后的variant_1条件跨越残差t不下降且仍>=2.0，说明挂单量坡度没有边际作用，'笔数-量背离'不是有效组成；(5) L3版variant_3与prototype方向相反且两者残差|t|>=2.0，说明机制不具深度连续性；(6) 任一完整genome的pfs < pfs_min=0.6，排序保真度不足。边界条件：机制只在每交易日最后一根30m提交对象上定义，不附加时段门控；若ask_volume1、ask_num_orders1等分母大量为0/缺失或三档深度为空，机制应退化而非增强。

## Round 1 / mechanism 2
- research_track: exploit
- parent_factor_ids: ["5857ca18f26c3a5b"]
- hypothesis: 在每交易日最后一根30m，修正父因子5857的单笔规模近似：显式用 bid_volume1/bid_num_orders1 与 ask_volume1/ask_num_orders1 分别刻画买卖两侧每笔挂单规模，替代仅用挂单量百分比变化的方向腿，并保留收盘价低于卖一价的报价缺口与买三挂单量增长；当买侧每笔挂单规模大于卖侧、收盘价仍在卖一价下方、远端买盘增长时，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，只用买一/卖一挂单量静态失衡预测次日收益", "传统父机制B：top-of-book order count imbalance (OCI)，只用买一/卖一委托笔数静态失衡预测次日收益"]
- falsifier: 以下任一观测即否定机制本身，而非仅分数较低：(1) 买侧单笔规模腿或卖侧单笔规模腿单独经整个 RefSet 条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或方向与事前符号相反且 |t| >= 2.0；(2) prototype 经整个 RefSet 联合回归条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或 spanning_r2 > spanning_r2_max=0.95，或 max_corr_refset >= corr_gate=0.6；(3) 删去卖侧单笔规模腿后残余 t 不下降且仍 >=2.0，说明卖侧显式拆细信息没有边际来源；(4) 任一完整 genome 的 pfs < pfs_min=0.6；(5) bid_num_orders1 或 ask_num_orders1 在样本中大量为0/缺失时机制应退化而非增强。

## Round 1 / mechanism 3
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，用收盘时点订单簿失衡相对全天均值的位置（obi - avg_obi）与收盘价差相对全天均值的偏移（spread_bps - avg_spread_bps）共同刻画尾盘流动性供给的时序状态；当收盘买方失衡高于自身日内常态且价差收窄时，说明流动性供给者在尾盘净买且不要求额外补偿，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：收盘静态 top-of-book OBI（order_book_imbalance），只用买一/卖一挂单量的截面水平预测次日收益", "传统父机制B：尾盘价格-成交额动量 close_reverse_price_amount_momentum_v1，只用已成交价格路径与成交额加权，不使用未成交委托供给的日内时序状态"]
- falsifier: 以下任一观测否定机制本身，而非仅分数较低：(1) 单独 OBI 时序腿或单独 spread 时序腿经 RefSet 条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或方向与事前设计相反且 |t| >= 2.0；(2) prototype 经整个 RefSet 联合回归条件跨越后 neutralized_rank_ic_tstat < 2.0，或 spanning_r2 > 0.95，或 max_corr_refset >= 0.6；(3) 删除 spread 腿后，剩余 OBI 腿的 spanning residual t 不下降且仍 >= 2.0，说明 spread 偏移无边际来源；(4) 任一完整 genome 的 pfs < 0.6；(5) difference(spread_bps, avg_spread_bps) 与 ratio(spread_bps, avg_spread_bps) 两种表达方向相反且各自 |t| >= 2.0，说明结论依赖标准化方式而非机制。

## Round 1 / mechanism 4
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，若尾盘平均单笔成交规模相对全天出现抬升（amount_last30m_share / deal_number_last30m_share 偏大），同时收盘时点微观价格相对收盘价有正溢价（买侧深度在价格尺度上占优），说明尾盘信息性大单仍在推动而非被卖方流动性完全吸收，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，只用收盘时点一档挂单量失衡，不区分尾盘大单与碎单结构。", "传统父机制B：daily average trade size (amount/deal_number)，只使用全天平均单笔成交额，不使用最后30分钟份额的相对偏离，也不与收盘时点价格加权失衡交互。"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) 大单腿或microprice_premium腿单独经整个RefSet条件跨越后 residual rankIC t < spanning_t_min=2.0，或方向与事前符号相反且|t|>=2.0；(2) prototype经整个RefSet条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或 spanning_r2 > spanning_r2_max=0.95，或 max_corr_refset >= corr_gate=0.6；(3) 删除microprice_premium腿后的变体在条件跨越后残差t不下降且仍>=2.0，说明价格加权失衡腿无边际贡献；(4) ratio与difference两种大单腿口径对应变体方向相反且各自残差|t|>=2.0，说明机制依赖测量单位而非微观结构；(5) 任一完整genome的pfs < pfs_min=0.6。

## Round 2 / mechanism 1
- research_track: exploit
- parent_factor_ids: ["85a184ef758ef2c3"]
- hypothesis: 在每交易日最后一根30m快照上，父因子85A184EF的'深度买盘-卖一挂单量'腿已被RefSet张成，因此将其机制深化为委托粒度结构：当买三单笔挂单规模（bid_volume3/bid_num_orders3）和买三相对卖一挂单量同时偏大、且卖一委托笔数相对卖一挂单量偏大（卖一被拆细）时，说明远端存在信息性大买单、而一档卖单只是碎单墙，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：top-of-book order book imbalance (OBI)，仅用买一/卖一挂单量的静态失衡预测次日收益", "传统父机制B：top-of-book order count imbalance (OCI)，仅用买一/卖一委托笔数的静态失衡预测次日收益"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) 完整prototype经整个RefSet条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0 或 spanning_r2 > spanning_r2_max=0.95，说明增量已被RefSet张成；(2) prototype或任一完整variant与任一RefSet单因子的 max_corr_refset >= corr_gate=0.6，说明只是crowded duplicate；(3) variant_1（去掉卖一碎单腿）或 variant_2（去掉买三单均规模腿）单独经条件跨越后方向与ex_ante_sign相反且|neutralized_rank_ic_tstat|>=2.0，说明'大单×碎单'配对的方向不成立；(4) variant_3（把卖一碎单腿换成卖二碎单腿）与prototype方向相反且两者残差|t|>=2.0，说明机制不具深度连续性；(5) 任一完整genome的 pfs < pfs_min=0.6，排序保真度不足。边界条件：机制只在每交易日最后一根30m提交对象上定义，不附加时段门控；若bid_num_orders3、ask_volume1等分母大量为0/缺失或三档深度为空，机制应退化而非增强。

## Round 2 / mechanism 2
- research_track: exploit
- parent_factor_ids: ["5857ca18f26c3a5b"]
- hypothesis: 在每交易日最后一根30m，把父因子5857的隔日反转腿从 pct_change(close) 换成收盘价相对当日VWAP的位置（ratio(close, vwap) 取负），并保留卖一挂单量收缩、收盘价低于卖一价的报价缺口和买一挂单量增长；当收盘价相对VWAP偏低、未出现尾盘VWAP溢价且收盘价仍在卖一价下方、卖一量收缩/买一量增长时，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: repair
- parents: ["传统父机制A：尾盘价格-成交额动量/隔日反转，仅用已成交价格路径与成交额加权", "传统父机制B：top-of-book OBI/OCI 与一档挂单量变化，仅用收盘时点静态失衡"]
- falsifier: 出现以下任一观测即否定机制本身而非仅分数较低：(1) 单独 -ratio(close, vwap) 经整个RefSet条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或单腿方向与事前负号相反且|t|>=2.0；(2) full prototype 经整个RefSet条件跨越后 neutralized_rank_ic_tstat < 2.0，或 spanning_r2 > spanning_r2_max=0.95；(3) full prototype 或任一完整 genome 与任一RefSet单因子的 max_corr_refset >= corr_gate=0.6；(4) 去掉报价缺口腿的 variant_2 残差t不下降且仍>=2.0，说明 difference(close, ask_price1) 无边际作用；(5) 把反转腿换回 -pct_change(close) 的 variant_3 与 -ratio(close, vwap) 的 prototype 方向相反且两者残差|t|>=2.0，说明机制依赖收益参考点选择而非微观结构；(6) 任一完整genome的 pfs < pfs_min=0.6。

## Round 2 / mechanism 3
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m，三档盘口在价格轴上的疏密结构独立于委托笔数与挂单量：当卖侧档位间距（ask_price2-ask_price1）相对买侧档位间距（bid_price1-bid_price2）更大时，价格向上需要穿透的卖单阶梯更稀疏，而下方承接阶梯更密集，次日收盘收益倾向为正。
- ex_ante_sign: +
- proposal_type: new_mechanism
- parents: ["传统父机制A：尾盘价格-成交额动量 close_reverse_price_amount_momentum_v1，只利用已成交价格移动与成交额加权，不读取未成交报价阶梯在价格轴上的间距。", "传统父机制B：top-of-book order book imbalance (OBI)，只利用买一/卖一挂单量的静态失衡，不利用二档相对一档的价格位置或疏密结构。"]
- falsifier: 以下任一观测否定机制本身： (1) price_gap_ask 单腿或 price_gap_bid 单腿中至少一个经 RefSet 条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或方向与假说相反且 |t| >= spanning_t_min=2.0； (2) prototype 或任一完整 variant 经整个 RefSet 联合回归条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或 spanning_r2 > spanning_r2_max=0.95，说明增量已被 RefSet 张成； (3) 任一候选与任一 RefSet 单因子 max_corr_refset >= corr_gate=0.6，说明只是拥挤重复； (4) difference 变体与 ratio 变体方向相反且各自残差 |t| >= spanning_t_min=2.0，说明结论依赖刻度而非机制； (5) 任一完整 genome 的 pfs < pfs_min=0.6。

## Round 2 / mechanism 4
- research_track: explore
- parent_factor_ids: []
- hypothesis: 在每交易日最后一根30m快照上，用上午相对下午的已实现波动率比（rv_am/rv_pm）与开盘30分钟相对尾盘30分钟的成交量占比比（volume_first30m_share/volume_last30m_share）共同刻画'早盘集中度'；当价格发现和成交活动过度集中于早盘、而尾盘活动萎缩时，说明当日情绪化/信息冲击已在早盘透支，次日收盘收益倾向为负。
- ex_ante_sign: -
- proposal_type: new_mechanism
- parents: ["传统父机制A：尾盘价格-成交额动量与日内趋势耗竭（close_reverse_price_amount_momentum_v1 / intraday_trend_exhaustion_v1），只使用分钟价格路径的一阶矩与成交额/成交笔数份额，不使用波动率二阶矩的上午/下午形状，也不使用开盘30分钟成交量份额。", "传统父机制B：收盘时点 top-of-book 订单簿失衡（order_book_imbalance / order_count_imbalance），只用买一/卖一挂单量与委托笔数的静态截面，不使用日内活动在开盘/尾盘之间的时间分配。"]
- falsifier: 出现以下任一观测即否定机制本身，而非仅分数较低：(1) prototype 经整个 RefSet 条件跨越后 neutralized_rank_ic_tstat < spanning_t_min=2.0，或 spanning_r2 > spanning_r2_max=0.95，说明预测力已被 RefSet 张成；(2) prototype 或任一完整变体与任一 RefSet 单因子的 max_corr_refset >= corr_gate=0.6，说明只是拥挤重复；(3) rv_am/rv_pm 单腿与 volume_first30m_share/volume_last30m_share 单腿经条件跨越后方向相反且各自残差 |t| >= 2.0，说明不存在统一的'早盘集中'机制；(4) 任一完整变体经条件跨越后残差方向与 ex_ante_sign 相反且 |t| >= 2.0，或 neutralized_rank_ic_tstat < spanning_t_min=2.0；(5) 任一完整 genome 的 pfs < pfs_min=0.6，排序保真度不足。
