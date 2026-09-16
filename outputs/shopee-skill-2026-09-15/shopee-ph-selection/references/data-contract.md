# 输入约定与可复用运行

`selection.json` 包含 `as_of`、`candidates`、`sources`、`observations`、`suppliers`、`profile`。日期必须ISO 8601并含时区；使用Decimal读取金额。

每候选包含id/name/spec/market_url/supply_url、fact/inference/recommendation/gaps、evidence_rows（维度、实际、阈值、程度、原因、来源）、`gates`字典及可选`model`。

八项gates：data、demand、competition、supply、logistics、compliance、cash、rights，值为通过/不通过/待补证。每项要有证据行；Python只处理已由Agent审阅的门槛，不能凭数值填“通过”。任一明确不通过拒绝，缺证保留，数学通过不能覆盖人工事实核验。

model必需键：net_sale_php、extra_subsidy_php、fx、quote_cny、purchase_units、purchase_surcharge_rate、setup_cny、test_orders、fee_lines、costs_reviewed、quote_evidence、quote_observed_at、quote_valid_until。quote_evidence须指向SKU级报价，quote_observed_at须为24小时内实际观察时间且不晚于运行时间；quote_valid_until不得过期。`costs_reviewed=true`仅在全部费用适用、基数、币种、单元、税项、分摊已经人工/Agent核查后设置；并非官方认证。

fee_lines完整键集合由脚本REQUIRED_COSTS定义，包括适用跨境佣金、交易费、分期额外费、增长、平台运费、处理、预售、活动、国内运费、仓包、SLS、广告、联盟、售后、收款、税、固定分摊、其他。每行：key、amount、currency（CNY/PHP）、evidence、valid_until、status（已核实/预算/不适用）、calculation（基数×率、舍入/封顶/分摊或明确不适用）。预算仅用于广告、联盟、售后、固定分摊和其他有说明费用；佣金/运费等不得用预算冒充核实。

压力：domestic、warehouse_pack、sls固定乘1.15；transaction必须额外填stress_amount，且在calculation中写明高档分期情景依据；其他费用可填stress_amount覆盖。同时换汇率×0.95，采购×1.10。成本金额都≥0；优惠与回收请先按定义净额处理并解释。

缺model则利润空白；不写0，也不写“预计能赚”。有完整预算model但关键gates未知时可算条件结果，仍不能进入批准队列。Python返回结果并由Excel呈现，修改模型须重新运行，Excel的单品测算区另提供相同加总/报价公式便于审核。

工具路径：现有环境可用Sorftime的shopee_product_search_from_name(site=PH)和ali1688_similar_product；调用前读取当时工具说明，保存原文/参数/时间。工具名和字段不是永久API保证，失败时不创建虚假返回。

运行（使用当前环境可用的Python和xlsxwriter/openpyxl）：

```text
python scripts/build_daily.py --input /path/selection.json --output /path/每日选品审核.xlsx
python scripts/test_selection_math.py
```

当前交付的22条是历史待补证案例，不是已通过model的样例。程序测试用的合成数字只存在tests函数中，禁止导出到真实候选或用来补齐10个验收名额。
