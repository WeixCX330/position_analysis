"""同一口径计算真实路径和模拟路径的指标；VaR/CVaR 是总体统计。"""
import numpy as np


METRICS = {
    "total_return": "累计收益", "annualized_return": "复合年化收益",
    "maximum_drawdown": "最大回撤", "annualized_volatility": "年化波动率",
    "sharpe_ratio": "夏普比率", "downside_volatility": "年化下行波动率",
}
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)


def path_metrics(paths, elapsed_years, risk_free_rate=0.0):
    paths = np.asarray(paths, dtype=float)
    if paths.ndim != 2 or paths.shape[1] < 2 or elapsed_years <= 0:
        raise ValueError("需要二维正净值路径及正的区间年数")
    if not np.isfinite(paths).all() or (paths <= 0).any():
        raise ValueError("路径出现非正值或溢出，请检查净值和模型参数")
    returns = paths[:, 1:] / paths[:, :-1] - 1
    log_ratio = np.log(paths[:, -1]) - np.log(paths[:, 0])
    total = np.expm1(log_ratio)
    vol = (returns.std(axis=1, ddof=1) * np.sqrt(252)
           if returns.shape[1] >= 2 else np.full(len(paths), np.nan))
    sharpe = np.divide(returns.mean(axis=1) * 252 - risk_free_rate, vol,
                       out=np.full(len(paths), np.nan), where=vol > 0)
    with np.errstate(over="raise", invalid="raise"):
        # 极小终值的total可能舍入成-1；直接用对数净值比，避免log1p(-1)丢失年化信息。
        annual = np.expm1(log_ratio / elapsed_years)
    return {
        "total_return": total, "annualized_return": annual,
        "maximum_drawdown": np.max(1 - paths / np.maximum.accumulate(paths, axis=1), axis=1),
        "annualized_volatility": vol, "sharpe_ratio": sharpe,
        "downside_volatility": np.sqrt(np.mean(np.minimum(returns, 0) ** 2, axis=1) * 252),
    }


def distribution(values):
    finite = np.asarray(values)[np.isfinite(values)]
    if not len(finite):
        return {"available": False, "reason": "少于2个日收益或波动为零，指标不可计算"}
    counts, edges = np.histogram(finite, bins=32)
    return {
        "available": True, "sample_count": len(finite),
        "percentiles": {f"p{int(q * 100):02d}": float(np.quantile(finite, q)) for q in QUANTILES},
        "histogram": {"edges": edges.tolist(), "counts": counts.tolist()},
    }


def percentile_rank(values, actual_value):
    """不超过真实值的有效模拟值占比；包含并列值，不把不可计算当成零。"""
    if actual_value is None or not np.isfinite(actual_value):
        return None
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    return float(np.mean(finite <= actual_value)) if len(finite) else None


def summarize(metrics, actual, confidence=0.95):
    losses = -metrics["total_return"]
    var = float(np.quantile(losses, confidence))
    tail = losses[losses >= var]
    # 精简接口的字段名固定为95，不能随主报告的--confidence改变含义。
    var_95 = var if confidence == 0.95 else float(np.quantile(losses, 0.95))
    return {
        "metric_distributions": {key: distribution(value) for key, value in metrics.items()},
        "loss_frequency": float(np.mean(metrics["total_return"] < 0)),
        "var_confidence": confidence, "var_loss": var, "cvar_loss": float(tail.mean()),
        "var_95_loss": var_95, "cvar_95_loss": float(losses[losses >= var_95].mean()),
        "actual_total_return_percentile_rank": percentile_rank(metrics["total_return"], actual["total_return"]),
        "actual_maximum_drawdown_percentile_rank": percentile_rank(
            metrics.get("maximum_drawdown", []), actual.get("maximum_drawdown")),
        "actual_sharpe_ratio_percentile_rank": percentile_rank(
            metrics.get("sharpe_ratio", []), actual.get("sharpe_ratio")),
    }


def build_backtest_output(result):
    """从同一次计算的完整结果导出约定的12项字段，不重跑模拟或用图表样例估算。"""
    period_codes = {
        "0": "1d", "1": "1w", "2": "1m", "3": "3m", "4": "1y",
        "5": "6m", "6": "3y", "7": "2y", "8": "4y", "9": "inception",
        "10": "5y", "11": "ytd", "12": "mtd", "13": "6y", "14": "10y",
        "15": "2m", "16": "4m", "custom": "custom",
    }
    distribution_fields = {
        "simulated_total_return_percentiles": "total_return",
        "simulated_maximum_drawdown_percentiles": "maximum_drawdown",
        "simulated_annualized_return_percentiles": "annualized_return",
        "simulated_sharpe_ratio": "sharpe_ratio",
    }
    scalar_fields = {
        "simulated_var_95_loss": "var_95_loss",
        "simulated_cvar_95_loss": "cvar_95_loss",
        "simulated_loss_frequency": "loss_frequency",
        "actual_total_return_percentile_rank": "actual_total_return_percentile_rank",
        "actual_maximum_drawdown_percentile_rank": "actual_maximum_drawdown_percentile_rank",
        "actual_sharpe_ratio_percentile_rank": "actual_sharpe_ratio_percentile_rank",
    }
    periods = []
    for period in result["periods"]:
        # 保留所选档位。模拟不可用时所有模拟结果均为null，原因查看完整result.json。
        simulation = period.get("simulation", {}) if period["available"] else {}
        distributions = simulation.get("metric_distributions", {})
        item = {"period": period_codes[period["date_type"]]}
        for field, metric in distribution_fields.items():
            dist = distributions.get(metric, {})
            quantiles = dist.get("percentiles", {}) if dist.get("available") else {}
            item[field] = {f"p{int(q * 100):02d}": quantiles.get(f"p{int(q * 100):02d}")
                           for q in QUANTILES}
        item.update({field: simulation.get(source) for field, source in scalar_fields.items()})
        periods.append(item)
    return {"product": {"prd_code": result["product_code"]}, "backtest": {"periods": periods}}
