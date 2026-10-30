# ranges.py 日期区间计算逻辑说明

本文对应同目录的 `ranges.py`，按实际代码解释日期选择、边界校验、回测步数及年数的计算。只说明现有行为，不修改计算规则。

## 1. 这个文件负责什么

`resolve_period()` 从已经整理好的历史数据中，确定一个回测区间：先算期望起止日，再寻找实际存在的日期，最后返回区间元数据 `meta` 和区间数据 `window`。

它不计算收益率、均值、波动率，也不执行随机模拟。这些工作分别由数据处理及模型代码完成。

调用顺序是：`run.py` 读取数据，调用 `resolve_period()` 划分区间，再交给 `models/backtest.py` 的 `evaluate_period()` 计算真实指标、估计参数和模拟结果。

## 2. 输入前提和参数

```python
def resolve_period(frame, date_type, end_date=None, start_date=None):
```

| 参数 | 含义 | 计算时的要求 |
| --- | --- | --- |
| `frame` | 完整历史数据表 | 非空；`date` 为日期时间类型，按时间升序排列，日期已去重。正常入口由 `load_nav()` 保证。 |
| `date_type` | 时间范围编号 | 可以传整数或字符串，函数内部统一转成字符串。 |
| `end_date` | 用户指定的目标终点 | 可不传；通常使用 `YYYY-MM-DD`。不传时取输入数据最后一天。 |
| `start_date` | 用户指定的目标起点 | 可不传；传入有效日期时按自定义区间处理，不再按编号推算起点。 |

函数自身不重新排序、不补交易日、不填充净值，也不判断输入最早日期是否等于产品真实成立日。

## 3. 时间编号与跨度

```python
DATE_TYPES = {
    "0": ("1天", "days", 1),
    # 其余定义见下表
}
```

每个编号对应三项：`(显示名称, 时间单位或特殊规则, 偏移量)`。

| 编号 | 名称 | 单位 / 规则 | 偏移量 | 起点的理论计算方式 |
| --- | --- | --- | --- | --- |
| `0` | 1天 | `days` | 1 | 目标终点减1个自然日 |
| `1` | 1周 | `days` | 7 | 目标终点减7个自然日 |
| `2` | 1个月 | `months` | 1 | 目标终点减1个日历月 |
| `3` | 3个月 | `months` | 3 | 目标终点减3个日历月 |
| `4` | 1年 | `years` | 1 | 目标终点减1个日历年 |
| `5` | 半年 | `months` | 6 | 目标终点减6个日历月 |
| `6` | 3年 | `years` | 3 | 目标终点减3个日历年 |
| `7` | 2年 | `years` | 2 | 目标终点减2个日历年 |
| `8` | 4年 | `years` | 4 | 目标终点减4个日历年 |
| `9` | 成立以来 | `since` | 0 | 前20条有效净值训练，以第20条日期作为回测起点 |
| `10` | 5年 | `years` | 5 | 目标终点减5个日历年 |
| `11` | 今年以来 | `ytd` | 0 | 目标终点所在年份的上一年12月31日 |
| `12` | 当月以来 | `mtd` | 0 | 目标终点所在月份的上个月最后一天 |
| `13` | 6年 | `years` | 6 | 目标终点减6个日历年 |
| `14` | 10年 | `years` | 10 | 目标终点减10个日历年 |
| `15` | 2个月 | `months` | 2 | 目标终点减2个日历月 |
| `16` | 4个月 | `months` | 4 | 目标终点减4个日历月 |

编号从 `0` 到 `16`，实际共有17档。编号顺序不是期限由短到长的顺序。

这些跨度采用自然日期规则。`1天` 不等于“最近一个交易日”，`1年` 不等于“固定252条收益”。最终模拟步数另按实际观测数计算。

## 4. 编号转换与合法性校验

```python
code = str(date_type)
if start_date is None and code not in DATE_TYPES:
    raise ValueError(f"未知 dateType: {code}")
```

`str()` 让整数 `4` 和字符串 `"4"` 使用同一套规则。没有指定自定义起点时，编号必须存在于 `DATE_TYPES`。

指定自定义起点后，日期起点由用户直接给出，因此这里不要求编号一定出现在固定档位表中。正常命令行入口为自定义区间传入 `"custom"`。

## 5. 目标终点 cutoff 与实际终点 end

```python
cutoff = pd.Timestamp(end_date).normalize() if end_date else frame.iloc[-1]["date"]
before_end = frame.loc[frame["date"] <= cutoff]
```

有 `end_date` 时，将其转换成 Pandas 日期，并用 `normalize()` 将时间归零，例如 `2026-10-30 15:20:00` 变成 `2026-10-30 00:00:00`。

没有指定终点时，直接采用输入数据最后一条日期，**不是电脑当天日期**。

`frame.loc[...]` 保留日期小于或等于目标终点的所有记录，确保不会选到终点之后的数据。

```python
if before_end.empty or (cutoff - before_end.iloc[-1]["date"]).days > 7:
    raise ValueError(...)
end = before_end.iloc[-1]["date"]
```

两种情况直接抛出异常：

1. 目标终点及之前没有任何有效记录。
2. 目标终点与之前最后一条记录相差超过7个自然日。

如果没有被拒绝，最后一条有效记录的日期就是实际终点 `end`。例如目标终点为周日，最后记录在周五，则实际终点取周五。相差恰好7天允许，8天不允许。

`cutoff` 和 `end` 可能不同。下面普通档、今年以来、当月以来的理论起点都依据 **`cutoff`** 推算，不会先把终点改成 `end` 再推算。

## 6. 推算目标起点 target

### 6.1 自定义区间

```python
if start_date:
    label, target, basis = "自定义区间", pd.Timestamp(start_date).normalize(), "custom"
```

自定义起点也转换成零点日期。这里设置的 `target` 仍然是目标起点，后续还要向前寻找不晚于它的有效观测，并执行缺口检查。

### 6.2 普通固定期限

```python
label, unit, amount = DATE_TYPES[code]
basis = "calendar_offset"
target = cutoff - pd.DateOffset(**{unit: amount})
```

例如编号 `"2"` 得到 `unit="months"`、`amount=1`，最后等价于：

```python
target = cutoff - pd.DateOffset(months=1)
```

`**{unit: amount}` 是 Python 的关键字参数展开写法：根据单位动态传入 `days=...`、`months=...` 或 `years=...`。

`DateOffset` 按日历减月份或年份，不把一个月固定成30天，也不把一年固定成365天。遇到目标月份不存在的日号，会落到该月最后一天，例如：

- `2026-03-31` 减1个月，得到 `2026-02-28`。
- `2024-02-29` 减1年，得到 `2023-02-28`。
- `2026-10-30` 减7天，得到 `2026-10-23`。

### 6.3 今年以来

```python
target = pd.Timestamp(year=cutoff.year, month=1, day=1) - pd.Timedelta(days=1)
```

先构造目标终点当年的1月1日，再减一个自然日，得到上一年的12月31日。例如终点在2026年，目标起点就是 `2025-12-31`。

这样做是为了使用年初之前的净值作为收益基准，包含当年第一条净值相对上一年末基准的收益。若从当年第一条净值直接开始算，会漏掉这一步收益。

如果上一年末没有净值，仍执行后面的向前寻找规则。程序不会直接改成当年第一条数据来缩短区间。

### 6.4 当月以来

```python
target = cutoff.replace(day=1) - pd.Timedelta(days=1)
```

先把目标终点的日号改成1，再减一个自然日，得到上个月最后一天。例如终点为 `2026-10-30`，目标起点是 `2026-09-30`。

目的和今年以来相同：保留计算本月第一步收益所需的上月末净值基准。

### 6.5 成立以来：前20条训练

```python
WARMUP_NAV_COUNT = 20

target, basis = before_end.iloc[0]["date"], "initial_20_nav"
if len(before_end) > WARMUP_NAV_COUNT:
    target = before_end.iloc[WARMUP_NAV_COUNT - 1]["date"]
```

这里的20是 **20条有效净值记录**，不是20个自然日。

如果截至终点有超过20条净值，使用索引 `20 - 1 = 19`，也就是第20条净值的日期作为回测起点。`iloc` 按位置取数，位置从0开始。

实际处理方式为：

| 数据位置 | 用途 |
| --- | --- |
| 第1至第20条净值 | 在模型文件中产生19个相邻日收益，用于估计均值和波动率 |
| 第20条净值 | 同时作为模拟路径的初始净值和真实回测收益的基准 |
| 第21条及之后净值 | 回测评价区间，不参与该档初始参数估计 |

这个日期文件只负责选出第20条记录；均值和波动率的计算发生在 `models/backtest.py` 的 `fit_model(..., warmup=True)`。

如果数据不超过20条，代码暂时把 `target` 设置为第一条日期，但后续会明确返回不可用，**不会真的从第一条开始模拟**。

## 7. 先构造默认不可用的元数据

```python
meta = {
    "date_type": code,
    "label": label,
    "requested_start": target.date().isoformat(),
    "requested_end": cutoff.date().isoformat(),
    "start_basis": basis,
    "historical_available": False,
    "available": False,
}
```

`date().isoformat()` 将日期输出为 `YYYY-MM-DD`，便于写入 JSON。

默认先将两个可用标记设置为 `False`。日期区间通过全部检查后，本文件只把 `historical_available` 改成 `True`；模拟是否可用，要等模型完成估参和模拟后再决定。

对于成立以来档，`requested_start` 保存的是按当前规则选择的训练结束日，并非输入最早日期；最早日期单独写在 `data_start` 中。

## 8. 成立以来的最少数据校验

```python
if basis == "initial_20_nav":
    meta.update(
        data_start=before_end.iloc[0]["date"].date().isoformat(),
        warmup_nav_count=WARMUP_NAV_COUNT,
    )
    if len(before_end) <= WARMUP_NAV_COUNT:
        meta["reason"] = ...
        return meta, frame.iloc[:0]
```

至少需要 `20 + 1 = 21` 条净值：前20条训练，至少再有1条才能评价起点之后的收益。

- 20条或更少：无法模拟回测。
- 21条：有1个回测收益间隔，具备日期层面的计算条件。
- 更多数据：回测从第20条持续到实际终点。

21条记录只是最低数量条件；如果后续模型发现训练波动率为零或其他异常，模拟仍然可能不可用。

`frame.iloc[:0]` 返回与原表具有相同列结构的空表，明确表示没有可用回测窗口。

## 9. 起点必须早于实际终点

```python
if target >= end:
    meta["reason"] = "起点不早于有效终点，没有完整收益区间"
    return meta, frame.iloc[:0]
```

至少要有前后两个不同日期，才能计算一段收益。如果目标起点等于或晚于实际终点，就直接返回不可用。

这里比较的是 `target` 和实际终点 `end`，不是目标终点 `cutoff`。

一个容易遇到的例子：目标终点是周六，实际最后净值在周五；`1天` 档的目标起点也是周五，因此 `target == end`，该档不可用。现有规则不会自动把“1天”改成“往前一个交易日”。

## 10. 将目标起点向前对齐到有效日期

```python
candidates = frame.loc[frame["date"] <= target]
if candidates.empty or (target - candidates.iloc[-1]["date"]).days > 14:
    meta["reason"] = "目标起点附近历史净值不足，不能缩短后冒充该期限"
    return meta, frame.iloc[:0]
start = candidates.iloc[-1]["date"]
```

从历史数据中找出所有不晚于目标起点的记录，再取其中最后一条，作为实际起点 `start`。

此处采用的是 **向前找已有记录**，不向后找记录，也不插值。例如目标起点在周日，假设之前最近一条记录是周五，则实际起点取周五。

以下情况不可用：

1. 目标起点及之前完全没有记录。
2. 找到的最近记录比目标起点早了超过14个自然日。

相差恰好14天允许，15天不允许。7天的终点容忍和14天的起点容忍都是当前代码设定，不是统一的交易所日历规则。

这也意味着缺少足够长的历史时，不会把“一年回测”自动缩成三个月回测。

## 11. 提取窗口并检查内部缺口

```python
window = before_end.loc[before_end["date"] >= start].copy()
```

`before_end` 已经限制了终点，再限制日期不早于实际起点，得到包含两端的区间：`start <= date <= end`。

`.copy()` 创建独立数据表，避免后续操作意外影响原始 `frame`。

```python
if window["date"].diff().dt.days.max() > 14:
    meta["reason"] = "历史区间内存在超过14个自然日的观测缺口"
    return meta, frame.iloc[:0]
```

计算过程分三步：

1. `diff()`：当前日期减去上一条日期，得到相邻观测的时间差。
2. `.dt.days`：将每个时间差转换为自然日数。
3. `.max()`：取区间里最大的相邻间隔，再判断是否超过14天。

第一条记录没有前一条，差值为空；`max()` 默认忽略这个空值。

周末和正常节假日不会被补成额外净值。区间中只要有一个相邻间隔超过14天，就拒绝该回测区间，避免把较长时间缺失的数据当成普通日频数据。

注意：本检查只覆盖选中的回测窗口。成立以来的前20条训练净值另由 `fit_model()` 检查；普通档起点前的训练区间没有在这个函数里执行同样的内部缺口检查。

## 12. 观测数、模拟步数和实际年数

```python
meta.update(
    start=start.date().isoformat(),
    end=end.date().isoformat(),
    historical_available=True,
    observation_count=len(window),
    steps=len(window) - 1,
    elapsed_years=(end - start).days / 365.2425,
)
return meta, window
```

### 12.1 观测数

`observation_count = len(window)` 是窗口内有效净值的条数，包含起点和终点。

### 12.2 模拟步数

`steps = len(window) - 1`，因为相邻两条净值才能产生一次收益。

例如窗口里有4条净值，就有3个间隔：第1条到第2条、第2条到第3条、第3条到第4条。因此模型模拟3步，而不是4步。

成立以来若输入100条净值，以第20条为起点，则窗口含第20至第100条，共 `100 - 20 + 1 = 81` 条净值，模拟 `81 - 1 = 80` 步。

模拟每一步对应一对相邻有效观测。它不会按自然日期差补出周六、周日或节假日的随机步。

### 12.3 实际跨度年数

`elapsed_years = (end - start).days / 365.2425`，以实际起终点的自然日差除以平均每年天数，将区间长度转换成年。

`365.2425` 是公历平均年长度，不是每年的固定自然日数。实际相隔365天时：

```text
elapsed_years = 365 / 365.2425 ≈ 0.999336 年
```

后续指标模块使用这个年数计算复合年化收益等指标，例如：

```text
复合年化收益 = (终点净值 / 起点净值) ** (1 / elapsed_years) - 1
```

年数依据实际 `start` 和 `end`，不直接把“1年”档强制写成 `1.0`，也不使用 `steps / 252`。

需要区分：模型中的日波动年化另使用 `sqrt(252)`；本文件的 `365.2425` 用于自然时间长度，两者含义不同。

## 13. 返回字段含义

| 字段 | 含义 |
| --- | --- |
| `date_type` | 当前档位编号；自定义时正常入口传入 `custom`。 |
| `label` | 档位显示名称。 |
| `requested_start` | 计算得到的目标起点，尚未向有效观测日期对齐；成立以来为特殊训练规则选定的目标。 |
| `requested_end` | 用户指定的目标终点；未指定时为输入最后日期。 |
| `start_basis` | `calendar_offset`、`initial_20_nav` 或 `custom`；今年以来和当月以来也归入 `calendar_offset`。 |
| `historical_available` | 是否通过历史区间检查，可用于计算区间真实表现。 |
| `available` | 模拟是否可用；本文件初始化为 `False`，由模型在模拟成功后改成 `True`。 |
| `reason` | 不可用的具体原因；成功划分窗口时本文件不写入此字段。 |
| `data_start` | 成立以来档使用的输入最早日期，不保证等于法律意义上的产品成立日。 |
| `warmup_nav_count` | 成立以来预留的训练净值条数，当前为20。 |
| `start` / `end` | 实际采用的有效起终日期，通过全部窗口检查后才写入。 |
| `observation_count` | 回测窗口内净值条数。 |
| `steps` | 回测窗口内相邻观测间隔数，即净值条数减一。 |
| `elapsed_years` | 实际自然日跨度除以365.2425。 |

## 14. 异常和不可用的区别

未知固定档位、终点没有可用记录或终点记录过旧，使用 `raise ValueError` 抛出异常。正常命令行入口会将其作为参数或数据错误结束本次运行。

成立以来记录不足、目标起点无法对齐、起点不早于终点、窗口内部缺口过长，则返回带 `reason` 的 `meta` 和空窗口。调用方可以继续处理其他档位。

因此，这个文件判断的是“是否有符合当前规则的历史区间”，不是“数据够不够可靠地估计风险”。即使 `historical_available=True`，模型仍可能因起点前训练数据不足、波动率无效等原因保留 `available=False`。
