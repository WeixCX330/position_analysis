# 单基金 POT 极值风险结果

状态：`data_validation_failed`

所有收益、损失、VaR、ES 均为小数：0.03 表示 3%。持有期限为一个观测交易日。

未计算原因：数据未达到计算要求：at_least_1000_daily_returns, at_least_three_calendar_years

数据：2026-09-28 至 2026-10-03，5 条日收益。

最低要求：1000条有效日收益及三年日期跨度，另检查日频和长缺口。

## 解释边界

- 日度VaR/ES不是月度累计收益或最大回撤，也不是最大可能亏损。
- 全样本拟合使用所有已知历史，不能冒充各历史时点的预测；样本外检验仅使用训练期拟合参数。
- 不填补日期缺口，不调整分红或拆分；累计净值不一定是分红再投资总回报，应核对数据口径。
- GPD是高阈值渐近近似；阈值、极值数量、结构变化及时间依赖会影响可靠性；拟合成功不是模型通过验证。
- Bootstrap采用固定20条观测的循环块（可用参数调整），置信区间仍是近似；二项检验未校正时间依赖。
- 原始收益包含上涨日对应的负损失；负VaR/ES不截零，不代表产品没有未来下跌风险。
- GPD外推可能超过单日100%损失的经济边界；此时报告异常标志而不截断或强行解释。
- 货币基金若仅提供每万份收益，按收益/10000处理，假设当日收益可再投资；不对每万份收益做涨跌幅。
- 单基金VaR不能直接相加或按权重求和得到组合VaR。

## 方法来源

实现依据：用户提供的《极值理论-POT方法.md》。
[SciPy GPD](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.genpareto.html)；
[SciPy 二项检验](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html)。
