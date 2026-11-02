# 单基金回测（精简独立版）

直接读取与本目录同级的 `../data_json/` 中的 **MCP响应JSON**，普通产品只用 `data.list[].date` 和 `navAccumulated` 两个字段计算；货币基金按日期和 `per10000Income` 逐期复投。默认路径以代码位置解析，不依赖终端当前目录。运行回测时不读取原CSV，也不调用旧项目或下载数据。使用**日频正态 GBM**，每档默认模拟一万条路径；普通档用起点前收益估参，成立以来档以前20条有效净值训练，从第20条净值开始模拟后续区间。

```text
选基工具代码4.0/
├── data_json/                  四份MCP格式数据和response.json
└── 单基金回测/
    ├── run.py                  唯一任务入口
    ├── date_ranges/ranges.py    dateType和自定义日期规则
    ├── models/data.py           读取MCP JSON、计算收益；也提供一次性CSV转换
    ├── models/backtest.py       参数估计和日频路径模拟
    ├── models/metrics.py        真实/模拟指标及分布、VaR/CVaR
    ├── analysis/analysis.py     画图、本地分析、可选LLM解读
    ├── frontend/page.py         可直接打开的HTML和交互图表
    ├── results/<run>/           本次全部输出
    ├── run_commands.txt         常用运行命令
    ├── test_backtest.py         关键数值、日期和无泄漏检查
    └── requirements.txt
```

## 运行

已有 `xuanjitools` 环境可直接运行，其他环境先安装依赖：

```bash
conda activate xuanjitools
cd 单基金回测
# 新环境才需要：python -m pip install -r requirements.txt
python run.py
python run.py --prdCode 001313 --dateType 4
python run.py --prdCode 002692 --dateType 4
python run.py --prdCode 015723 --dateType 9
python run.py --prdCode 150005 --dateType 9
python run.py --date-type 0 1 2 15 16
python run.py --date-type 4 --end-date 2025-12-31
python run.py --start-date 2025-09-10 --end-date 2026-09-10
# 使用真实MCP响应文件（产品编号支持字母）
python run.py --json ../data_json/response.json --prdCode SMLC01 --dateType 2
# 直接通过标准输入接收JSON，不必先转换CSV
cat ../data_json/response.json | python run.py --json - --prdCode SMLC01 --dateType 2
```

`--json` 替换输入文件，相对路径以终端当前目录解析。未指定时按 `--prdCode` 自动读取与代码目录同级的 `data_json/fund_nav_<编号>.json`，与当前工作目录无关；两者都不指定则使用001313。`--prd-code`、`--fund-code` 是 `--prdCode` 的别名；`--date-type` 是 `--dateType` 的别名。原来的 `--csv`、`--nav-column` 已移除。默认截止日是JSON最后有效日期，本地样例为 **2026-09-10**；不会补造数据到系统当天。指定终点时，最近有效记录距目标日超过7天则报错。

## MCP格式和四份数据

MCP请求参数由工具侧负责，示例的正确JSON写法为：

```json
{"dateType":"2","prdCode":"SMLC01","sortRule":"1"}
```

本程序读取工具**响应**，不调用未配置的MCP服务。响应示例：

```json
{
  "data": {
    "prdName": "示例产品",
    "totalNum": 2,
    "list": [
      {"date": "20260928", "navAccumulated": "1.1756", "navUnit": "1.1756"},
      {"date": "20260929", "navAccumulated": "1.0437", "navUnit": "1.0437"}
    ]
  },
  "responseCode": "000000",
  "responseMsg": "success",
  "Thread": "local-example"
}
```

`date` 必须为 `YYYYMMDD`；数字字符串直接转数值。记录无论正序还是倒序都统一按日期升序处理，`sortRule` 不参与模型。`navUnit`、`prdName`、`Thread` 不参与收益计算；名称仅用于展示。失败响应、无效累计净值、同日冲突数值、`totalNum` 与实际条数不一致都会报错，避免把未取完的分页当成完整历史。程序不会用 `navUnit` 偷换缺失的 `navAccumulated`。响应可能不带 `prdCode`，这时用原请求的 `--prdCode` 传入。

如果已在Python里拿到MCP返回对象，可直接调用 `models.data.load_nav(response_dict)`，不需要落盘或转换CSV。

| 本地JSON | 来源与计算口径 |
| :--- | :--- |
| `fund_nav_001313.json` | 原CSV的2732条日期、累计净值；保留单位净值但计算时忽略 |
| `fund_nav_002692.json` | 原CSV的2494条日期、累计净值 |
| `fund_nav_015723.json` | 原CSV的1057条日期、累计净值 |
| `fund_nav_150005.json` | 货币基金，5216条连续日期和每万份收益；没有披露累计净值 |

150005的记录形如 `{"date":"20090104","per10000Income":"0.6845"}`。内部按 `指数[t] = 指数[t-1] × (1 + 每万份收益[t]/10000)` 复投，首个观测水平归一为1；首条观测作为起点，后续区间收益从第二条起计算。不能把每万份收益本身当价格做相邻涨跌。原CSV的2004—2008年有收益期间缺口和重叠，所以导出时排除了1169条，只保留2009年起已核验连续的部分；JSON额外的 `sourceInfo` 记录这一原因，页面明确显示“每万份收益复投指数”。原CSV不改动。

四份文件是本地格式样例，不是真实MCP调用记录；`sourceInfo.mock=true` 用于标记来源。`Thread` 是本地源文件哈希生成的追踪标识。需要重新从四个CSV生成时，单独运行 `python models/data.py`，输出到项目根目录的 `data_json/`；普通回测不会执行转换或回读CSV。

**数据长度要求**：普通档默认至少需要起点前 **2个日收益**，可用 `--min-training` 提高。成立以来档单独采用**前20条有效净值训练**，并至少再有1条用于回测，所以截至所选终点至少需要 **21条净值**。20条净值产生19个日收益，用于估计均值和样本标准差；“20”按有效记录数计算，不是自然日。该档训练窗口固定，不受普通档 `--train-window`、`--min-training` 控制。如果MCP只给一个月数据，也不能据此模拟更长历史或补造起点前收益。

例如用户这份6条净值：2026-09-28至2026-10-03，成立以来因不足21条而不可用；一天档回测10月2日至3日、用起点之前的3个收益拟合，仍可模拟。一天路径只有一个日收益，因此该路径的年化波动率、夏普不可计算；累计收益、最大回撤、下行波动、亏损频率和VaR/CVaR仍可计算。小样本会在结果和页面中明确提示不稳定。

已经在 `单基金回测` 目录内时，使用 `python run.py --json ../data_json/response.json --prdCode SMLC01 --dateType 0 9`；在项目根目录则使用 `python 单基金回测/run.py --json data_json/response.json --prdCode SMLC01 --dateType 0 9`。

## dateType 对照

用户列出的编号是0到16，共 **17种**。原文未填完的今年以来/当月以来分别补为11和12。

| dateType | 范围 | 起点规则 |
| :--- | :--- | :--- |
| 0 | 1天 | 目标终点向前1个自然日，匹配之前最近有效净值；周一通常匹配上周五 |
| 1 | 1周 | 向前7个自然日 |
| 2 | 1个月 | 向前1个日历月 |
| 3 | 3个月 | 向前3个日历月 |
| 4 | 1年 | 向前1个日历年 |
| 5 | 半年 | 向前6个日历月 |
| 6 | 3年 | 向前3个日历年 |
| 7 | 2年 | 向前2个日历年 |
| 8 | 4年 | 向前4个日历年 |
| 9 | 成立以来 | 预留前20条有效净值训练，第20条净值作为回测起点，之后模拟到终点 |
| 10 | 5年 | 向前5个日历年 |
| 11 | 今年以来 | 上年12月31日的最近有效净值作为基点 |
| 12 | 当月以来 | 上月末的最近有效净值作为基点 |
| 13 | 6年 | 向前6个日历年 |
| 14 | 10年 | 向前10个日历年 |
| 15 | 2个月 | 向前2个日历月 |
| 16 | 4个月 | 向前4个日历月 |

普通档起点在目标日或之前14天内匹配；历史不够则该档不可用，不截短后冒充完整期限。区间内超过14天无有效记录也标不可用。第9档不需要外部成立日期，但最早20条记录用于训练，实际回测起点是第20条净值日；不把训练期收益混入回测结果。训练段有超过14天的缺口也不拟合。

## 模型和指标

随机游走的起点是**历史起点的净值**，不是某一天的收益率。先算相邻有效净值的简单收益 `S[t]/S[t-1]-1` 和对数收益 `log(S[t]/S[t-1])`，再估计均值和样本标准差：

- 普通档：只取 `date < 回测起点` 的最近252个日对数收益，属于起点前估参的样本外对照；`--train-window` 可修改窗口。
- 成立以来（dateType=9）：以前20条净值产生的19个日对数收益估参（包含截至第20条净值日已知的收益），从第20条净值出发模拟第21条至终点；起点之后的任何收益都不参与拟合。至少需要21条净值，不足时明确不可用。
- 普通档至少2个日收益，可用 `--min-training` 提高限制；成立以来固定使用19个收益。波动为零仍不可拟合。少于60个样本会提示结果不稳定，能计算不等于参数可靠。

```text
log(S[t+1]/S[t]) = daily_log_mean + daily_log_std × Z[t]
Z[t] ~ N(0, 1)
```

均值已经是对数收益均值，不再重复减去半方差。每一步对应一个有效基金净值观测间隔，不补周末或交易所假日。252日用于波动率、夏普和模型参数年化；复合年化收益按实际区间自然日数/365.2425换算。

JSON的 `periods[].fit.calibration_mode` 为普通档记录 `pre_origin_out_of_sample`，为成立以来记录 `initial_20_nav_out_of_sample`。该档 `data_start` 是输入最早日期，`start` 是第20条净值日期，`fit.training_nav_start` 至 `training_end` 是20条净值训练区间，`training_observations=19`。`actual` 和所有模拟统计只评价 `start` 至 `end`，首段训练期不计入这项收益。页面和分析文字显示“前20条训练”，不会再写成样本内拟合。

每条真实/模拟路径计算 **6类指标**：累计收益、复合年化收益、最大回撤、年化波动率、夏普比率、年化下行波动率。模拟结果分别保存五档分位P5/P25/P50/P75/P95和32箱完整直方图。此外汇总终点亏损路径频率、终点损失VaR/CVaR、真实累计收益所在模拟百分位。VaR/CVaR本身是全体路径的统计值，不再声称有“一万条VaR”。

仅一个日收益时，样本标准差和夏普不可计算，会返回不可用。下行波动以0为目标。夏普使用年化算术平均简单收益减 `--risk-free-rate`（默认0），再除以年化简单收益标准差。`--confidence` 默认0.95；损失 `L=-累计收益`，VaR是L的置信分位，CVaR是L不低于VaR的路径平均值。所有路径盈利时VaR/CVaR可能为负，不截为0。

短区间年化波动和夏普很不稳定，尤其1天/1周；年化收益也只是换算。单个固定起点不构成多起点滚动验证，不对客户亏损、行业成因或未来收益下结论。

## 结果

每次运行新建一个目录，输出以下文件（无可模拟档时不生成静态图）：

| 文件 | 用途 |
| :--- | :--- |
| `result.json` | 唯一完整结果：输入来源、配置、各档真实指标、模拟分布、风险汇总、画图摘要和分析状态 |
| `backtest_output.json` | 约定的12项业务字段，结构为 `product.prd_code` 和 `backtest.periods[]`，适合单独传给下游模型或接口 |
| `daily_returns.csv` | 选定终点及之前的日期、净值、重算日收益和对数收益 |
| `path_metrics.npz` | 全部模拟路径的6类指标数组；不保存全部完整净值路径，避免占大量空间 |
| `charts.png` | 300 DPI六联分布图；优先一年档，否则第一个可模拟档；无可模拟档则不生成 |
| `charts.svg` | 同一张六联分布图的矢量版本，可放大或导入文档 |
| `charts_meta.json` | 六联图所用档位、数据摘要、配色、分箱及输出参数 |
| `analysis.md` | 本地分析，启用LLM且成功时追加大模型解读 |
| `report.html` | 双击打开，切换区间；SVG净值路径、终点损失及6类指标分布图，不依赖服务器或CDN |

JSON路径示例：`periods[].actual.total_return` 是真实累计收益，`periods[].simulation.metric_distributions.total_return.percentiles.p05` 是模拟P5，`periods[].simulation.var_loss`、`cvar_loss` 是对应 `var_confidence` 的损失统计。`available` 表示模拟可用，`historical_available` 表示真实区间可用；两者分开。不可用值是 `null` 或明确状态，绝不补0。

`report.html` 内嵌生成 `result.json` 时的同一份结果，不是在浏览器打开时重新读取磁盘 JSON。页面增加“精简字段 JSON”链接；额外导出不会重新抽样或改变历史起点、训练窗口和模拟路径。

`backtest_output.json` 的字段定义见 [docs/backtest_output_fields.md](docs/backtest_output_fields.md)，`simulated_sharpe_ratio` 保持约定名称，内容为五档分位对象。P05/P25/P50/P75/P95 和最大回撤、夏普分位直接使用全部路径指标的统计结果；三个真实值百分位统一使用“有效模拟值不超过真实值”的比例（包含并列值）。最大回撤百分位通常越高表示真实回撤相对更深，夏普百分位通常越高表示真实风险调整后表现相对更好。

精简文件的 `simulated_var_95_loss` / `simulated_cvar_95_loss` 始终按95%计算；`--confidence` 只控制完整报告的 `var_loss` / `cvar_loss`。不会把99%结果放入名称含95的字段。

精简文件保留所有本次选中的档位；不可模拟的档位保留 `period`，其余统计值和五档分位子值为 `null`，具体失败原因仍查看 `result.json`。一天档仅夏普相关字段不可计算时，这些字段为 `null`，其他可用指标照常输出。`period` 与 `dateType` 的映射为：`0→1d`、`1→1w`、`2→1m`、`3→3m`、`4→1y`、`5→6m`、`6→3y`、`7→2y`、`8→4y`、`9→inception`、`10→5y`、`11→ytd`、`12→mtd`、`13→6y`、`14→10y`、`15→2m`、`16→4m`，自定义区间为 `custom`。实际起止日期、可用性、无风险利率等上下文仍在完整文件中，精简文件不额外添加字段。

原有运行命令不变，重新运行即会在新目录同时生成两份 JSON；旧结果目录不会自动更新。

### 图表样式与离线导出

图表配色、字体、坐标和图例规则直接写在 `frontend/page.py` 与 `analysis/analysis.py` 中，无需安装 Codex skill 或额外 Python 包。图形采用白底、蓝色模拟分布、橙色真实值，以及不同线型区分真实值和分位线；这是一般科研图表样式，不表示已满足某个期刊的投稿要求。

- 页面各图可下载当前档位的 SVG，导出图包含标题、日期、单位、样本量和必要说明。前端图形不依赖 Matplotlib、网络或外部 JavaScript 包。
- 净值图支持线性或明确标注的 log10 对数轴。线性轴按全部展示曲线自动定范围，不强制从零开始；展示最多10条模拟样例，不代表概率带。
- 指标分布沿用原始32箱统计，柱高为箱内路径数除以该指标有效路径数，不是概率密度。P05/P50/P95 是跨路径情景分位，不是估计参数的置信区间。
- 真实值超出模拟直方图范围时扩展横轴，不裁切真实值或尾部；可通过当前档位数值表核对全部五档分位。
- 终点损失图将累计收益直方图按 `L=-R` 镜像，沿用原计数；VaR/CVaR 直接读取计算结果，保留符号。图中尾部阴影仅辅助定位，不用于重算尾部概率或指标。
- VaR 为负、CVaR 为正可以同时成立：分位阈值仍盈利，但更差尾部路径平均已亏损。不能将它们取绝对值或强制改成相同符号。
- 静态 `charts.svg` / `charts.png` 只对应一个选定档位，不随页面下拉框切换；下载页面各图的 SVG 才对应当前选中档位。

修改绘图代码后需重新运行 `run.py` 才会生成新版报告，既有结果目录中的 HTML 和图片不会自动更新。

NPZ可直接读取，不需要pickle：

```python
import numpy as np
values = np.load("results/<run_directory>/path_metrics.npz", allow_pickle=False)
one_year_drawdowns = values["4_maximum_drawdown"]  # 10,000条最大回撤
```

## 可选大模型分析

默认不联网。服务支持常见的 `POST /chat/completions` 格式即可，所有配置来自环境变量；这里只发送数值摘要，不发送原始JSON和完整模拟路径。

```bash
export LLM_API_KEY='你的密钥'
export LLM_BASE_URL='https://你的服务地址/v1'
export LLM_MODEL='你的模型名'
python run.py --date-type 4 --llm
```

缺配置、调用失败或正文被截断，保留本地分析；查看 `result.json` 的 `analysis.llm_status.used` 才能知道是否真实用了大模型。

## 验证

```bash
python -m pytest test_backtest.py -q
```

检查MCP响应状态/条数/日期校验、累计净值计算且不使用单位净值、每万份收益正确复投、日期规则、防止使用终点后收益、GBM已知分布、VaR/CVaR、短区间不可用指标和随机种子复现。
