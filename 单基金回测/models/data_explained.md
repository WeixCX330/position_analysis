# data.py 数据读取与收益率计算说明

本文逐段解释当前 `data.py`，不修改源代码。重点是输入数据怎样变成模型使用的净值、日简单收益和日对数收益。

相关文档：[回测模型](backtest_explained.md)、[指标计算](metrics_explained.md)、[日期划分](../date_ranges/ranges_explained.md)。

## 1. 文件职责和两种运行方式

| 函数 / 入口 | 用途 | 正常回测是否执行 |
| --- | --- | --- |
| `load_nav(json_source)` | 读取并校验 MCP JSON，生成内部净值及收益序列 | 是，由 `run.py` 调用 |
| `convert_csvs(project_root=None)` | 把原项目四个 CSV 转换成 MCP 格式 JSON 样例 | 否，只在主动调用时执行 |
| `if __name__ == "__main__"` | 直接运行本文件时调用 `convert_csvs()`，打印生成路径 | 不属于正常 JSON 回测流程 |

正常回测计算只使用日期及累计净值；货币基金使用日期及每万份收益。`navUnit` 不参与计算。

## 2. 输入是字典还是文件路径

```python
if isinstance(json_source, dict):
    payload, filename = json_source, None
    raw_bytes = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
else:
    path = Path(json_source).expanduser().resolve()
    raw_bytes, filename = path.read_bytes(), str(path)
    payload = json.loads(raw_bytes.decode("utf-8-sig"))
```

- 传入字典：直接把它作为 JSON 对象；同时序列化为 UTF-8 字节，供后面的 SHA-256 追溯使用。`allow_nan=False` 禁止序列化非标准 JSON 数值，如 `NaN`。
- 传入路径：`expanduser()` 展开 `~`，`resolve()` 得到绝对路径，读取文件原始字节。`utf-8-sig` 可以兼容带 UTF-8 BOM 的文件。
- `filename=None` 表示输入来自内存对象，没有文件路径。

这一步不计算金融指标，也不向 MCP 服务发请求；它读取的是已经拿到的响应。

## 3. 校验响应和记录数量

依次校验以下条件：

1. 响应必须是字典，且 `responseCode` 必须严格等于字符串 `"000000"`。
2. `data` 必须是字典，`data.list` 必须是数组。
3. `list` 不能为空，每条记录都必须是字典。
4. `totalNum` 不能是布尔值，转换成字符串后必须全部为数字，转成整数后必须等于数组长度。

```python
int(total) == len(rows)
```

数量不一致时拒绝计算，避免只读取一页就当成完整历史。比如 `totalNum=1000`，但数组只有100条，会报错；`totalNum="1000"` 可以接受。

这里检查的是去重前的原始记录数量。它只能发现总数与返回数组不符，不能证明服务端报告的总数一定正确。

## 4. 选择计算字段：按整个输入选择，不逐行混用

```python
column = "navAccumulated" if any(
    r.get("navAccumulated") is not None for r in rows
) else "per10000Income"
```

只要任意一条记录含非 `None` 的 `navAccumulated`，整份数据就选择累计净值模式，每条记录都必须有有效累计净值。

所有记录都没有非空累计净值时，整份数据才选择 `per10000Income` 模式。

因此，不能在某天用累计净值、另一天用每万份收益，也不会在累计净值缺失时偷偷改用 `navUnit`。

```python
isinstance(r.get(column), (str, int, float))
```

选定字段允许数字或数字字符串，明确排除布尔值。Python 中布尔值也属于整数类型，所以代码另行判断 `bool`。

## 5. 日期、数值与正值校验

先构造两列表：`date` 和临时计算列 `value`。

```python
"date": [str(r.get("date", "")) for r in rows]
```

日期先转成字符串，再要求匹配8位数字，所以字符串 `"20261028"` 和整数 `20261028` 均可进入后续日期解析；`"2026-10-28"` 不符合这里的输入格式。

```python
pd.to_datetime(..., format="%Y%m%d", errors="coerce")
pd.to_numeric(..., errors="coerce")
```

`errors="coerce"` 先把无效日期或数值标记为空值。随后统一检查日期为空、数值非有限等情况，**报错而不是删除这些记录或补零**。

`np.isfinite()` 排除 `NaN`、正无穷和负无穷。然后按字段校验范围：

| 模式 | 必须满足 | 原因 |
| --- | --- | --- |
| 累计净值 | `value > 0` | 后续要做比值和对数，不能为零或负数 |
| 每万份收益 | `value > -10000` | 保证 `1 + value / 10000 > 0`，复投因子为正 |

负的每万份收益可以进入计算，但不能低至每万份亏损10000或更多。

## 6. 同日冲突、去重与排序

```python
(frame.groupby("date")["value"].nunique() > 1).any()
```

按日期分组，统计每一天不同数值的数量。只要某一天存在两个不同计算值，就报错，不擅自挑选一个。

同日同值的重复记录允许去重：

```python
frame.drop_duplicates("date").sort_values("date").reset_index(drop=True)
```

去重后按日期升序排列，并重新生成从0开始的行号。至少保留两个不同日期，否则没有一段完整收益可算。

该处理不检查遗漏了哪些交易日，不补日期，不前向填充净值，也不会把节假日制造成零收益样本。

## 7. 普通产品：内部净值直接取累计净值

```python
frame["nav"] = frame["value"]
basis = "reported_accumulated_nav"
```

例如累计净值依次为 `1.00、1.02、1.01`，内部 `nav` 原样使用这三个值。

这里没有重新复权或分红再投资处理。披露累计净值不一定等于严格的分红再投总回报净值，因此后续收益的经济含义取决于输入净值口径。

## 8. 货币基金：从每万份收益构造复投指数

```python
levels = (1 + frame["value"] / 10000).cumprod()
frame["nav"] = levels / levels.iloc[0]
basis = "per_10000_income_reinvestment_index"
```

设第 `t` 条每万份收益为 `I_t`，定义当期收益因子：

```text
g_t = 1 + I_t / 10000
levels_t = g_0 × g_1 × ... × g_t
nav_t = levels_t / levels_0
```

因此：

```text
nav_0 = 1
nav_t = g_1 × ... × g_t    （t ≥ 1）
```

第一条记录只充当内部指数的基准；它的收益因子在归一化时被约掉。由于没有更早一天的净值，第一条收益不会作为已知区间收益保留下来。

举例：输入每万份收益 `0.30、0.40、0.50`：

| 位置 | 每万份收益 | 内部 nav | 从上一条到本条的收益 |
| --- | ---: | ---: | ---: |
| 第1条 | 0.30 | 1 | 无前一条，收益为空 |
| 第2条 | 0.40 | 1.00004 | 0.00004，即0.004% |
| 第3条 | 0.50 | `1.00004 × 1.00005 = 1.000090002` | 0.00005，即0.005% |

**不能对 `0.30、0.40、0.50` 本身计算涨跌幅。** 那会得到“每万份收益金额的变化率”，而不是基金投资收益率。

该公式假设每条每万份收益可按对应一期再投资。加载函数没有读取收益所属期间字段；如果一条记录合并了多个自然日，它仍只形成一个观测间隔，不会自动拆分为多日收益。

重建后再次检查 `nav` 全部有限且大于零，防止累计乘积溢出或数值下溢为零。

## 9. 日简单收益率

```python
frame["daily_return"] = frame["nav"].pct_change(fill_method=None)
```

设 `P_t` 为本条内部净值，`P_(t-1)` 为前一条净值：

```text
R_t = P_t / P_(t-1) - 1
```

例如从100涨到110：`110 / 100 - 1 = 0.10`，表示10%；再从110跌到99：`99 / 110 - 1 = -0.10`，表示亏损10%。

`fill_method=None` 表示计算前不自动填充缺失值。第一条没有前一条净值，结果为 `NaN`，不是0。

这里“日”实际上指相邻有效记录间隔。周五至周一、节假日或数据缺口仍只形成一条收益，不按间隔自然日数开方或摊分。

## 10. 日对数收益率

```python
frame["daily_log_return"] = np.log(frame["nav"] / frame["nav"].shift())
```

`shift()` 将净值整体向后移动一行，使当前行能对应上一行净值。

```text
r_t = ln(P_t / P_(t-1)) = ln(1 + R_t)
R_t = exp(r_t) - 1
```

对数使用自然对数。上涨10%时，`r_t = ln(1.1) ≈ 0.09531018`；下跌10%时，`r_t = ln(0.9) ≈ -0.10536052`。

两者不是同一个数值，只有涨跌很小时才近似相等。对数收益可以相加：

```text
r_1 + ... + r_T = ln(P_T / P_0)
区间累计简单收益 = exp(r_1 + ... + r_T) - 1
```

`backtest.py` 用对数收益估计均值和标准差；`metrics.py` 计算路径波动率、夏普等指标时，重新从路径净值计算简单收益。

`load_nav()` 可以一次性生成整份历史的收益列，但每条收益只引用当前与前一条净值。是否使用未来信息由后续估参筛选日期决定，不是“整列预先计算”本身造成泄漏。

注意：当前代码在生成这两列后没有再做一次全列有限值检查。极端净值比例仍可能发生浮点溢出；后续部分步骤会校验，但本文件不保证已拦截所有异常比例。

## 11. 产品信息与追溯字段

`sourceInfo` 缺省为 `{}`；如果提供，则必须是字典。

产品编号优先取 `data.prdCode`，没有有效值时再取 `sourceInfo.prdCode`。非空编号必须为字符串，防止 `001313` 被整数格式破坏前导零。产品名称存在时也必须是字符串。

返回 `source` 的计数字段：

```text
input_rows = 原始 list 条数
valid_rows = 日期去重后条数
duplicate_rows_removed = input_rows - valid_rows
```

这里没有“删除无效记录再继续算”的过程；无效日期、数值或冲突会直接报错。因此正常成功时，删除数量就是同日同值的重复条数。

```python
hashlib.sha256(raw_bytes).hexdigest()
```

SHA-256 是输入字节的追溯摘要，不是金融计算，也不是加密。文件输入摘要基于原始文件字节；字典输入摘要基于重新序列化后的字节。即使数据含义一样，空格、键顺序等字节不同，摘要也可能不同。

`start_date`、`end_date` 是整份已排序输入最早及最晚日期，不是某一档的回测起终点。`conversion_info` 原样保存来源说明，不参与收益计算。

## 12. load_nav 的返回结果

```python
return frame, source
```

`frame` 删除临时 `value` 后，保留四列：

| 列 | 单位 / 含义 | 第一条是否有值 |
| --- | --- | --- |
| `date` | 有效观测日期 | 有 |
| `nav` | 累计净值，或以1为基准的货币基金复投指数 | 有 |
| `daily_return` | 相邻观测的简单收益，小数 | 无，`NaN` |
| `daily_log_return` | 相邻观测的自然对数收益 | 无，`NaN` |

若有 `N` 条净值，通常得到 `N - 1` 条有效收益。

## 13. convert_csvs：一次性生成本地 JSON 样例

### 13.1 路径与产品清单

```python
tool_dir = Path(__file__).resolve().parents[1]
root = Path(project_root) if project_root else tool_dir.parent
output = root / "data_json"
```

本文件位于 `单基金回测/models/data.py`，因此 `parents[1]` 指向 `单基金回测`，再上一层为项目根目录。输出 `data_json` 与 `单基金回测` 同级。

转换固定四个产品：`001313、002692、015723、150005`。读取项目根目录下的 CSV 和产品资料表；运行普通 JSON 回测不依赖这些 CSV 或资料表。

### 13.2 CSV 读取及排序

```python
pd.read_csv(csv_path, dtype=str, keep_default_na=False).sort_values("date")
```

全部按字符串读取，避免编号前导零或原始小数文本被隐式转换。空字符串不自动变成 `NaN`。日期列按字符串排序，前提是原 CSV 使用统一可排序的日期格式。

`original_count = len(raw)` 记录筛选前数量，不是收益样本数。

### 13.3 150005 的特殊筛选和期间连续性校验

```python
raw = raw.loc[raw["date"] >= "2009-01-01"].copy()
```

这条规则是针对当前150005样例源数据的已知问题：2004—2008年期间记录存在缺口或重叠，所以只导出2009年起的区间。它不是所有货币基金通用的成立日期规则。

读取 `period_start_date` 为各期开始日、`date` 为各期结束日，然后检查：

```text
每期开始日 <= 当期结束日
第i期开始日 - 第i-1期结束日 = 1个自然日    （从第二期起）
```

相邻期恰好衔接才通过；大于1天意味着有缺口，小于1天意味着重叠或重复。

两侧 `.reset_index(drop=True)` 是为了按相邻位置相减，避免 Pandas 按原索引对齐。`errors="raise"` 表示无法解析期间日期时直接报错。

该连续性条件不要求每期本身都只有1天。加载生成的 JSON 时又不保留期间起日，因此跨多日期间仍会按一个观测处理，这是当前实现的口径限制。

### 13.4 字段映射与数量

| 原 CSV 字段 | 输出 JSON 字段 | 是否参与正常回测 |
| --- | --- | --- |
| `date` | 转成 `YYYYMMDD` 的 `date` | 是 |
| `accumulated_nav` | 普通产品 `navAccumulated` | 是 |
| `unit_nav` | 普通产品 `navUnit` | 否，仅保留展示字段 |
| `per_10000_income` | 货币基金 `per10000Income` | 是 |

数量对应：

```text
totalNum = exportedRows = len(records)
originalRows = 原 CSV 行数
excludedRows = originalRows - exportedRows
```

普通产品这里不筛选历史；货币基金的剔除数量来自上述2009年起点限制。

`Thread` 取原始 CSV 文件 SHA-256 十六进制摘要的前32个字符，作为样例追溯标识，不是实际 MCP 服务生成的会话编号。

最后用 `ensure_ascii=False` 保留中文，`indent=2` 缩进，`allow_nan=False` 禁止非标准 JSON 数值，写入 `data_json/fund_nav_<编号>.json`。现有同名文件会被覆盖。

## 14. 数据边界

本文件最低只要求两条有效日期记录，不要求三年或1000条数据。三年及1000条收益门槛属于另一个极值理论工具，不适用于当前 `load_nav()`。

本文件不执行客户交易、手续费、持仓权重、产品基准或底层资产计算。生成的是单产品净值收益，不能直接当成客户账户真实收益。
