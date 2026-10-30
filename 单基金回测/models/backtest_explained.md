# backtest.py 估参、随机模拟与回测执行说明

本文逐段解释当前 `backtest.py` 的全部计算过程，不修改代码。

相关文档：[输入数据与收益率](data_explained.md)、[六项指标及总体统计](metrics_explained.md)、[回测日期划分](../date_ranges/ranges_explained.md)。

## 1. 本文件的三个函数

| 函数 | 输入 | 计算任务 | 返回 |
| --- | --- | --- | --- |
| `fit_model()` | 完整历史数据、回测起点、训练规则 | 筛选训练收益，估计日对数收益均值及标准差 | 参数字典 `fit` |
| `simulate()` | 起点净值、步数、模型参数、路径数和种子 | 生成随机路径，逐路径计算六项指标 | 指标数组、展示索引、少量展示路径 |
| `evaluate_period()` | 一个档位的日期信息和历史窗口 | 先计算真实表现，再估参和模拟，最后汇总对照结果 | 该档结果、全部模拟指标数组 |

回测的历史区间已经发生。模拟是在历史起点用当时可用数据建立模型，再对照之后的真实结果。这里不是从当前日期向未来延长路径。

## 2. 统一符号和时间单位

| 符号 | 含义 |
| --- | --- |
| `P_t` | 相邻有效观测的净值，货币基金为内部复投指数 |
| `R_t = P_t/P_(t-1)-1` | 简单收益 |
| `r_t = ln(P_t/P_(t-1))` | 对数收益；模型估参和随机抽样使用它 |
| `n` | 实际使用的训练收益数量 |
| `m` | 训练日对数收益均值 |
| `s` | 训练日对数收益样本标准差 |
| `T` | 本次回测的收益间隔数，即模拟步数 |
| `M` | 模拟路径总数，命令行默认10000 |
| `Y` | 实际起终日期自然日差除以365.2425 |

一个模拟步对应历史窗口中一对相邻有效观测。即使跨周末或节假日，也仍然只走一步，不按自然日拆开。

## 3. fit_model 的参数

```python
def fit_model(frame, origin, train_window=252, min_training=2, warmup=False):
```

- `frame` 是已经按日期升序整理的完整历史，包含 `daily_log_return`。
- `origin` 是日期模块选出的实际回测起点，不一定等于用户传入的目标日期。
- `train_window=252` 是普通档最多使用252条日对数收益，不是固定252个自然日，也不是一定使用252条净值。
- `min_training=2` 是普通档最低数值估参条件，不代表两个样本就有可靠预测能力。
- `warmup=True` 表示成立以来档，切换到前20条净值训练规则。

## 4. 普通档：只用起点前收益估参

```python
sample = frame.loc[
    frame["date"] < pd.Timestamp(origin),
    ["date", "daily_log_return"],
]
sample = sample.dropna().tail(train_window)
```

按以下顺序执行：

1. 只取日期严格小于回测起点的记录。
2. 只保留日期和日对数收益两列。
3. 删除空收益，通常最早一条净值没有前一条，所以对应收益为空。
4. 从剩余记录末尾取最近 `train_window` 条。

收益的日期标在“当前净值日”。例如6月10日对应的收益是6月9日净值到6月10日净值的变化。如果回测起点是6月10日，普通档会排除这条6月10日收益，仅使用更早日期标记的收益。

这比“截至起点已知数据”更保守：**起点当日以及起点之后的收益都不用于估参**。

如果起点前有400条有效收益，默认取最近252条；如果只有80条，取80条；不足 `min_training` 才报错。

对应模式：`calibration_mode="pre_origin_out_of_sample"`。

注意：普通档在这里没有重新检查训练区间的相邻日期是否超过14个自然日；日期模块的缺口检查覆盖的是回测评价窗口，不能误认为所有普通档训练数据都已按同样规则检查。

## 5. 成立以来：前20条净值产生19条训练收益

```python
history = frame.loc[frame["date"] <= pd.Timestamp(origin)]
if len(history) != WARMUP_NAV_COUNT:
    raise ValueError(...)
```

此分支包含起点当天，要求截至起点恰好20条净值。日期模块将第20条记录选为回测起点，因此正常情况下这20条就是输入最早的20条。

```python
if history["date"].diff().dt.days.max() > 14:
    raise ValueError(...)
```

检查这20条训练净值的最大相邻日期间隔，超过14个自然日则报错。

```python
sample = history.iloc[1:][["date", "daily_log_return"]].dropna()
if len(sample) != WARMUP_NAV_COUNT - 1:
    raise ValueError(...)
min_training = WARMUP_NAV_COUNT - 1
```

排除没有前值的第一条净值，余下第2至第20条对应19个对数收益：

```text
ln(P_2/P_1), ln(P_3/P_2), ..., ln(P_20/P_19)
```

当前规则固定要求19条有效训练收益，不受普通档 `train_window`、`min_training` 参数调整影响。

第20条净值既是训练末日，也是模拟起点。模拟第一个收益间隔对应第20条到第21条，第21条及之后真实收益不参与初始参数估计。

对应模式：`calibration_mode="initial_20_nav_out_of_sample"`。

因此，成立以来和普通档的起点边界不同：普通档用 `< origin`，成立以来用 `<= origin`。成立以来不是从第一条净值开始评价完整收益，前19个间隔用于训练。

## 6. 均值与标准差的实际公式

```python
if len(sample) < min_training:
    raise ValueError(...)
mean = float(sample["daily_log_return"].mean())
std = float(sample["daily_log_return"].std(ddof=1))
```

设训练收益为 `r_1, ..., r_n`：

```text
m = Σr_i / n
s = sqrt( Σ(r_i - m)^2 / (n - 1) )
```

`ddof=1` 表示样本标准差分母是 `n-1`。成立以来用19个收益，因此均值分母19、方差分母18。

`m` 和 `s` 都是每个观测日的尺度，既不是月度，也不是年化值。它们基于对数收益，不是简单收益。

示例：净值 `100 → 110 → 99 → 108.9`，三个对数收益约为：

```text
0.09531018, -0.10536052, 0.09531018
m ≈ 0.028419948
s ≈ 0.115857280
```

对应简单收益是 `10%、-10%、10%`，其均值与标准差不是以上数值。此例只为核对公式，不表示三条数据足以建立可靠模型。

```python
if not np.isfinite(std) or std <= 0:
    raise ValueError(...)
```

标准差为零、负数或非有限值时拒绝估参。因此即使训练收益全部稳定为正，只要完全相等导致标准差为零，当前工具也不会退化成一条确定性增长路径继续模拟。

当前检查显式验证的是 `std`，不是分别对训练均值做完整有限值检查。正常数据通常不会有问题，但不能将它描述成对所有极端数值输入的完整兜底。

## 7. fit 中三个年化参数怎样计算

```python
"daily_log_mean": mean,
"daily_log_std": std,
"annual_log_drift": mean * 252,
"annual_volatility": std * np.sqrt(252),
"annual_gbm_mu": mean * 252 + 0.5 * std * std * 252,
```

| 字段 | 公式 | 含义 |
| --- | --- | --- |
| `daily_log_mean` | `m` | 每步对数收益均值 |
| `daily_log_std` | `s` | 每步对数收益样本标准差 |
| `annual_log_drift` | `252m` | 按252步换算的一年对数增长漂移，不是复合年化收益率 |
| `annual_volatility` | `s√252` | 年化对数收益波动参数 |
| `annual_gbm_mu` | `252m + 0.5 × 252s²` | 连续时间GBM中的年化净值漂移参数 `μ` |

对应 GBM 关系：

```text
dP/P = μ dt + σ dW
日对数增量均值 m = (μ - σ²/2) / 252
日对数增量标准差 s = σ / sqrt(252)
所以 σ = s sqrt(252)，μ = 252m + 0.5σ²
```

模拟函数直接使用 `m`、`s` 抽日对数增量，**不会再扣一次 `σ²/2`**。年化字段是参数解释，不会替代每日参数重新走另一套模拟。

`training_start` / `training_end` 是最早和最晚训练收益的标记日期；最早训练收益还引用前一条净值。因此 `training_start` 不一定是训练所需最早净值日。

成立以来另返回 `training_nav_count=20`、`training_nav_start`，明确最早训练净值与训练收益起日的区别。

## 8. simulate：初始化随机数与展示索引

```python
rng = np.random.default_rng(seed)
chunks = {key: [] for key in METRICS}
```

创建局部随机数生成器，用给定种子产生随机数。相同环境、相同参数、相同种子有助于复现结果；不依赖外部全局 `np.random.seed()` 状态。

`chunks` 为六个指标各创建一个分批结果列表，不保存所有路径的完整历史。

```python
indices = np.unique(
    np.linspace(0, steps, min(121, steps + 1)).astype(int)
)
```

计算展示时保留哪些净值点：

1. 原始路径点索引为 `0..steps`，共 `steps + 1` 个。
2. 最多取121个均匀分布的位置；不足121个则取全部点。
3. 浮点索引转整数；这里非负，效果为向下取整。
4. `np.unique()` 去重，确保索引不重复。

首点0和末点 `steps` 会保留。这只是绘图抽样，不减少真实模拟步数，也不减少指标计算所用的路径点。

## 9. 分批生成随机路径

```python
for offset in range(0, path_count, 1000):
    count = min(1000, path_count - offset)
```

每批最多1000条路径。总数10000时运行10批；总数2500时依次生成1000、1000、500条。

分批主要降低内存占用，不改变每条路径计算完整窗口的原则。

### 9.1 抽取每日对数增量

```python
shocks = rng.normal(
    fit["daily_log_mean"],
    fit["daily_log_std"],
    (count, steps),
)
```

`shocks` 形状为 `(本批路径数, 模拟步数)`。每个元素：

```text
z_(j,t) ~ N(0,1)
X_(j,t) = m + s × z_(j,t)
```

虽然变量叫 `shocks`，它已经包含均值 `m`，不是单独的零均值冲击。代码按独立正态增量抽样，训练期的波动聚集、厚尾和时间相关性没有在这里保留。

### 9.2 对数增量累加后转成净值

```python
values = start_nav * np.exp(np.cumsum(shocks, axis=1))
```

对每条路径累加至当前步，再取指数：

```text
P_(j,t) = P_0 × exp(X_(j,1) + ... + X_(j,t))
等价递推：P_(j,t) = P_(j,t-1) × exp(X_(j,t))
单步简单收益 = exp(X_(j,t)) - 1
```

它是乘法随机过程，不是 `前日净值 + 随机收益率`，也不是把简单收益直接累加。

例如起点100，两个对数增量为 `0.01、-0.02`：

```text
第一步：100 × exp(0.01) ≈ 101.005017
第二步：100 × exp(0.01 - 0.02) ≈ 99.004983
```

公式不引用回测窗口之后的真实净值，只使用起点净值、训练参数和随机数。真实未来路径仅用于后面的历史对照。

计算被 `np.errstate(over="raise", invalid="raise")` 包围，遇到溢出或无效运算抛错；极端下溢产生零净值会被后续指标输入正值检查拒绝。

### 9.3 把初始净值补回完整路径

```python
paths = np.concatenate(
    (np.full((count, 1), start_nav), values),
    axis=1,
)
```

`values` 只有模拟后的第1至第T步，代码在最左边补一列起点净值，所以 `paths.shape=(count, steps+1)`。同批所有路径从相同净值开始。

`axis=1` 表示按时间列拼接，不是增加路径条数。

## 10. 每条完整路径算指标，再保留少量绘图数据

```python
computed = path_metrics(paths, years, risk_free_rate)
for key in chunks:
    chunks[key].append(computed[key])
```

先用完整路径调用 `metrics.py`：累计收益、复合年化收益、最大回撤、年化波动率、夏普和年化下行波动率，每条路径各得到一个值。

每批计算后只收集六项指标的数组。最大回撤先在完整路径上计算，绝不是从最多121个绘图点反推。

```python
if offset == 0:
    samples = paths[:10, indices].tolist()
```

只从第一批提取前10条路径，再按展示索引保留净值点。它们只是样例，不是挑出的最佳、最差或最接近中位数的路径，也不是全部10000条路径。

```python
return {key: np.concatenate(value) for key, value in chunks.items()}, indices, samples
```

最终把各批同一指标的一维结果拼接，得到六个各长 `M` 的数组。

例如10000条路径：指标数组保存6×10000个结果，但展示路径最多只有10条、每条最多121个点。分位数和风险指标来自全部路径的指标数组，不能根据图上10条线推算总体分布。

`simulate()` 不在返回值中保存所有完整净值路径，也不生成逐日路径分位带。

## 11. evaluate_period：先判断有无真实历史窗口

```python
result = dict(meta)
if not meta["historical_available"]:
    return result, {}
```

先复制日期元数据。如果日期模块判断窗口不可用，保留不可用原因，不计算真实或模拟指标，返回空模拟指标字典。

`dict(meta)` 是浅拷贝；当前日期元数据主要是标量，因此这里用来避免直接改写传入字典。

## 12. 先计算真实路径的六项指标

```python
years = meta["elapsed_years"]
actual_values = path_metrics(
    window["nav"].to_numpy()[None, :],
    years,
    config["risk_free_rate"],
)
```

真实净值列原本是一维 `(T+1,)`。`[None, :]` 在最前面增加一个维度，变为 `(1, T+1)`，就能与模拟路径复用同一函数。

```python
float(value[0]) if np.isfinite(value[0]) else None
```

因为真实只有一条路径，取每个指标数组的第一个值。有限值转为普通浮点数；不可用值转为 `None`，输出 JSON 时为 `null`。

真实指标在模型训练之前就计算。即使起点前训练样本不足、不能模拟，历史窗口可用时仍可以保留真实表现。

## 13. 提示信息和初始真实绘图数据

根据条件添加说明：

- `years < 1`：提醒不足一年区间的年化只是数学换算。这里判断实际年数，不看档位名称；自然日差365除以365.2425也略小于1。
- `start_basis == "initial_20_nav"`：设置 `warmup=True`，提醒前20条净值用于训练。
- `steps < 2`：只有一个收益时，波动率与夏普不可计算；不代表所有六项指标都为空。

```python
plot_indices = np.unique(
    np.linspace(0, len(window)-1, min(121, len(window))).astype(int)
)
```

按与模拟展示相同的原则，先保存最多121个真实净值和日期。此时模拟路径列表为空，即使之后拟合失败仍有真实曲线数据。

## 14. 拟合失败时返回什么

```python
try:
    fit = fit_model(..., warmup=warmup)
except ValueError as exc:
    result["reason"] = str(exc)
    return result, {}
```

捕获估参函数的 `ValueError`，写入原因并返回。此时典型状态是：

```text
historical_available = True
available = False
actual = 已计算的真实指标
chart_data = 真实曲线，没有模拟路径
reason = 起点前样本不足、波动率为零等
```

不能把 `available=False` 解释成没有历史数据；它只表示模拟没有完成。

此处局部捕获只包围 `fit_model()`；真实指标或后续模拟的数值异常不在这个 `try` 中，可能由外层入口处理并结束整次运行。

## 15. 每个档位的随机种子

```python
seed = (
    config["seed"] + (int(meta["date_type"]) + 1) * 100003
    if meta["date_type"].isdigit()
    else config["seed"] + 999983
)
```

数字编号使用：

```text
档位种子 = 基础种子 + (编号+1) × 100003
```

例如基础种子为20261029，编号0对应20361032，编号4对应20761044。

非数字编号，例如自定义区间 `custom`，使用基础种子加999983。

这些偏移是人为设置的可复现规则，用来区分不同档位的随机数流，不是金融公式，也不是均值或风险调整。

种子没有包含产品编号或自定义起止日期，所以不同产品若同一档位、同种子和同步数，会使用相同的标准正态随机抽样结构，只是均值、波动率与净值起点不同。不同自定义窗口也不会自动获得专属种子。

## 16. 执行模拟与汇总

```python
metrics, indices, samples = simulate(
    float(window.iloc[0]["nav"]),
    meta["steps"],
    fit,
    config["paths"],
    seed,
    years,
    config["risk_free_rate"],
)
```

各参数含义：

- 起点净值：取真实历史窗口第一条内部净值。
- 步数：实际有效净值条数减一，不是日期相差的自然日数。
- 模型：当前档独立估计的 `m` 和 `s`。
- 路径数：默认10000条，正常命令行要求至少1000条。
- 实际年数：仅传给指标计算，不用于改变正态抽样的每步尺度。
- 无风险收益：仅影响路径夏普，不影响随机路径生成。

```python
result.update(
    available=True,
    fit=fit,
    path_count=config["paths"],
    simulation_seed=seed,
    simulation=summarize(metrics, result["actual"], config["confidence"]),
)
```

模拟与汇总正常完成后才标记 `available=True`。`summarize()` 在全部模拟路径的指标上计算五档分位、直方图、区间终点亏损频率、VaR/CVaR和真实收益百分位，详细公式见 `metrics_explained.md`。

当前 `confidence` 默认0.95，所以 VaR/CVaR 默认对应95%损失尾部；它不改变正态随机抽样，也不改变固定五档分位。

## 17. 将模拟索引映射回真实日期

```python
result["chart_data"] = {
    "dates": window.iloc[indices]["date"].dt.strftime("%Y-%m-%d").tolist(),
    "actual_nav": window.iloc[indices]["nav"].tolist(),
    "sample_paths": samples,
}
```

模拟步数与历史观测间隔数一致，因此相同索引可以取出对应真实日期和真实净值。第0点对应回测起点，第T点对应真实窗口终点。

真实观测间隔可能跨多个自然日，但模型仍对每个间隔使用同一个日对数均值和标准差；这里只做日期标签映射，没有按周末或假期调整随机增量方差。

## 18. 训练数量警告，不是额外拒绝门槛

```python
if fit["training_observations"] < 60:
    ...
elif fit["training_observations"] < 252:
    ...
```

| 实际训练收益数 | 行为 |
| --- | --- |
| 少于当前模式最低值 | `fit_model()` 报错，不模拟 |
| 达到最低值但不足60 | 模拟完成，提示样本很少、结果不稳定 |
| 60至251 | 模拟完成，提示不足252条收益 |
| 至少252 | 不添加以上两类数量提示 |

60和252在这里是提示分界，不是默认计算必须满足的硬门槛。成立以来固定19个收益，所以正常完成时仍会有不足60的警告。

## 19. 返回值如何进入最终文件

```python
return result, metrics
```

`result` 是该档位的日期、真实指标、拟合参数、模拟分布、提示和少量展示路径，会进入总 `result.json`。

`metrics` 是六个逐路径指标数组。`run.py` 按档位和指标命名后写入压缩的 `path_metrics.npz`，例如 `4_total_return`。它保存的是每条路径的指标，不是所有路径的每日完整净值。

成立以来若输入100条净值，总体数量关系为：

```text
训练净值：第1至第20条，共20条
训练收益：第2至第20条对应的19条
评价净值：第20至第100条，共81条
模拟步数：80
默认路径：10000条
每条完整路径净值点：81
六项逐路径指标：每项10000个值
展示路径：最多10条
展示日期点：此例81个；长区间最多121个
```

## 20. 一份数据到底怎样走完整个计算过程

1. `data.py`：JSON的日期和数值，转换为内部净值、简单收益和对数收益。
2. `ranges.py`：确定实际起终点、真实净值窗口、模拟步数及自然年数。
3. `evaluate_period()`：用窗口真实净值计算六个真实指标。
4. `fit_model()`：只筛选允许的训练期对数收益，计算 `m` 和 `s`。
5. `simulate()`：抽取独立正态对数增量，累加、取指数，得到每条完整净值路径。
6. `metrics.path_metrics()`：按真实路径相同的公式计算每条模拟路径的六项指标。
7. `metrics.summarize()`：汇总全部路径，计算分位、直方图、终点损失风险及真实结果百分位。
8. `run.py`：保存 JSON、逐路径指标文件，再调用分析和前端模块输出报告。

这里没有在每个回测日重新估参，没有滚动窗口更新模型，也没有把真实的下一日收益加入模拟。当前是“每个档位在起点拟合一次，再固定参数模拟到终点”。

模型不包含客户交易、申赎费用、持仓权重、市场基准、厚尾冲击或动态波动率。结果描述当前净值口径和固定参数GBM下的历史对照，不能仅凭真实结果位于某个分位就断言客户亏损的具体原因。
