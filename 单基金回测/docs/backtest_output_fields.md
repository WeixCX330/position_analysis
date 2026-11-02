# 回测输出字段说明

按截图第二列整理，共 12 项业务字段。补齐最后两行的优先级、英文名称和描述，并将“夏普比率分为”改为“夏普比率分位”。为便于复制，字段表和完整 JSON 分开展示。

`[]` 表示数组元素；`{p}` 表示 `p05`、`p25`、`p50`、`p75`、`p95` 五个分位子键。点号表示层级路径，不是 JSON 键名的一部分。收益、损失、回撤和概率均用小数表示，例如 `0.03` 表示 3%；夏普比率没有百分比单位。

| 字段优先级 | 中文名称 | 英文 (Python snake_case) | 英文 (Java camelCase) | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| P0 | 回测产品编号 | `product.prd_code` | `product.prdCode` | 本份回测所属的产品或份额类别编号，用于关联客户持仓与已有产品数据。使用字符串，保留前导零；不同份额类别不得直接混用结果。 |
| P0 | 回测档位 | `backtest.periods[].period` | `backtest.periods[].period` | 回测历史区间的档位标识，例如 `1y`、`3y`、`5y`、`inception`。它不等于客户实际持有期，也不是 `dateType` 参数编码；具体起止日期由调用上下文提供。 |
| P0 | 回测模拟终点累计收益分位 | `backtest.periods[].simulated_total_return_percentiles.{p}` | `backtest.periods[].simulatedTotalReturnPercentiles.{p}` | 每条模拟路径计算终点相对起点的累计简单收益 `R = V_end / V_start - 1`，再对全部有效路径取五档分位。`p05`、`p50`、`p95` 分别是收益的第 5、50、95 百分位；P50 是中位数，不是平均收益。这是模型条件下的路径结果分布，不是参数的置信区间。 |
| P0 | 回测模拟路径最大回撤分位 | `backtest.periods[].simulated_maximum_drawdown_percentiles.{p}` | `backtest.periods[].simulatedMaximumDrawdownPercentiles.{p}` | 对每条完整路径计算 `MDD = max_t(1 - V_t / max_{s≤t} V_s)`，再取五档分位。峰值必须发生在谷值之前。回撤用非负数表示，越大说明期间峰谷跌幅越深；它不等于终点亏损，也不是未来最大可能损失的上限。 |
| P0 | 回测模拟终点损失 VaR95 | `backtest.periods[].simulated_var_95_loss` | `backtest.periods[].simulatedVar95Loss` | 令每条路径的终点损失 `L = -R`，取损失的第 95 百分位。衡量所选完整回测期限的终点损失门槛；只有回测期限为一天时才是单日口径。同一分位算法下等于累计收益 P05 的相反数。允许为负，负值表示该门槛对应的仍是收益，不取绝对值、不截断为零。 |
| P0 | 回测模拟终点尾部平均损失 CVaR95 | `backtest.periods[].simulated_cvar_95_loss` | `backtest.periods[].simulatedCvar95Loss` | 对满足 `L ≥ VaR95` 的路径取损失平均值，衡量较差尾部情景下的平均损失程度。与 VaR 使用同一批路径、同一期限和符号口径；可为负，不代表最大损失。需要路径终点数据，不能仅由几个分位点推算。有限样本出现并列值时，参与平均的路径比例可能不恰好为 5%。 |
| P0 | 回测模拟亏损路径频率 | `backtest.periods[].simulated_loss_frequency` | `backtest.periods[].simulatedLossFrequency` | 终点累计收益 `R < 0` 的有效路径数除以全部有效路径数，范围为 0–1。表示当时起点与模型参数条件下的模拟终点亏损频率；不是途中发生回撤的比例，也不能直接当作客户未来亏损概率。0 和 1 均不构成现实保证。 |
| P0 | 真实收益所在模拟百分位 | `backtest.periods[].actual_total_return_percentile_rank` | `backtest.periods[].actualTotalReturnPercentileRank` | 同一历史区间内，模拟终点累计收益不超过真实累计收益的路径比例，即 `count(R_sim ≤ R_actual) / N`，范围为 0–1，包含并列值。例如 0.12 表示真实收益位于该模拟分布偏低的一侧；它不是收益率、预测准确率或显著性检验的 p 值。 |
| P0 | 回测模拟终点年化收益分位 | `backtest.periods[].simulated_annualized_return_percentiles.{p}` | `backtest.periods[].simulatedAnnualizedReturnPercentiles.{p}` | 每条路径按实际回测时长计算复合年化收益 `(V_end / V_start)^(1 / Y) - 1`，其中 `Y` 为实际区间折算的年数，再取五档分位。短区间年化只是数学换算，可能放大短期波动；不能与累计收益直接混比，也不是未来一年收益承诺。 |
| P0 | 回测模拟终点夏普比率分位 | `backtest.periods[].simulated_sharpe_ratio.{p}` | `backtest.periods[].simulatedSharpeRatio.{p}` | 每条路径结束后，使用该路径完整区间的日简单收益计算年化夏普比率：`(日收益均值 × 252 - 年化无风险利率) / (日收益样本标准差 × √252)`，再对有效夏普比率取五档分位。它不是终点那一天的夏普比率。无风险利率由计算配置或上下文提供；不足两个日收益或波动率为零时不可计算。沿用截图字段名，该字段是分位对象，不是单个数值。 |
| P0 | 真实最大回撤所在模拟最大回撤百分位数 | `backtest.periods[].actual_maximum_drawdown_percentile_rank` | `backtest.periods[].actualMaximumDrawdownPercentileRank` | 同一区间内，模拟最大回撤不超过真实最大回撤的有效路径比例，即 `count(MDD_sim ≤ MDD_actual) / N`，范围为 0–1，包含并列值。通常越高表示真实回撤相对模型情景越深；例如 0.98 表示 98% 的模拟路径回撤不大于真实回撤。它不是回撤幅度；若实际与全部模拟回撤均为零，按此规则也会得到 1，需结合实际值及并列情况解释。 |
| P0 | 真实夏普比率所在模拟夏普比率百分位数 | `backtest.periods[].actual_sharpe_ratio_percentile_rank` | `backtest.periods[].actualSharpeRatioPercentileRank` | 同一区间、同一收益频率和无风险利率下，模拟夏普比率不超过真实夏普比率的有效路径比例，即 `count(Sharpe_sim ≤ Sharpe_actual) / N_valid`，范围为 0–1，包含并列值。通常越高表示真实风险调整后表现相对模拟结果越好；它不是收益率或预测准确率。真实夏普不可计算或没有有效模拟夏普时返回 `null`。 |

## 输出 JSON 示例

沿用截图可见的数值；截图没有提供的结果使用 `null`，不补造数据。仅包含上述 12 项业务字段及必要的父节点、分位子键，已移除未列入第二列的 `start`、`available`、`annualized_return` 等字段。

```json
{
  "product": {
    "prd_code": "150005"
  },
  "backtest": {
    "periods": [
      {
        "period": "1y",
        "simulated_total_return_percentiles": {
          "p05": 0.015649791323946893,
          "p25": null,
          "p50": 0.017224600155636538,
          "p75": null,
          "p95": 0.018823245777218445
        },
        "simulated_maximum_drawdown_percentiles": {
          "p05": null,
          "p25": null,
          "p50": null,
          "p75": null,
          "p95": null
        },
        "simulated_var_95_loss": null,
        "simulated_cvar_95_loss": null,
        "simulated_loss_frequency": 0.0,
        "actual_total_return_percentile_rank": 0.0,
        "simulated_annualized_return_percentiles": {
          "p05": 0.015660269780042833,
          "p25": null,
          "p50": 0.01723614195820311,
          "p75": null,
          "p95": 0.0188358686792496
        },
        "simulated_sharpe_ratio": {
          "p05": null,
          "p25": null,
          "p50": null,
          "p75": null,
          "p95": null
        },
        "actual_maximum_drawdown_percentile_rank": null,
        "actual_sharpe_ratio_percentile_rank": null
      }
    ]
  }
}
```

## 使用说明

- 最后两个百分位字段已加入计算：均以有效模拟指标不超过对应真实指标的比例计算，包含并列值；夏普不可计算时返回 `null`。上方示例仍保留截图数值和缺失值，仅用于展示格式，不是新版程序的实际运行结果。
- `null` 表示未提供或不可计算，不能按 0 解释。截图中已有的 `0.0` 保留为真实零值。
- `run.py` 每次运行额外生成 `backtest_output.json`，按本文结构输出，不修改任何约定字段名；完整结果仍保存为 `result.json`。已有 P25、最大回撤和夏普分位直接复用同次模拟的全部路径统计，不使用前端抽取的10条样例估计。
- `simulated_var_95_loss` 和 `simulated_cvar_95_loss` 固定使用95%置信水平，即使完整报告传入其他 `--confidence`，这两个字段的含义也不变。
- 精简文件保留本次选择的所有档位，不可模拟的档位保留 `period`，其余统计值和分位子值均为 `null`；具体原因查看同目录 `result.json`。一天档没有足够日收益计算夏普时，仅夏普相关结果为 `null`。
- 按要求未额外加入起止日期、无风险利率、可用性或数据质量字段；使用方仍需从调用上下文获得这些信息，才能正确比较区间和解释结果。
