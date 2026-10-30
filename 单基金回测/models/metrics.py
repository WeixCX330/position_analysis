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


def summarize(metrics, actual, confidence=0.95):
    losses = -metrics["total_return"]
    var = float(np.quantile(losses, confidence))
    tail = losses[losses >= var]
    return {
        "metric_distributions": {key: distribution(value) for key, value in metrics.items()},
        "loss_frequency": float(np.mean(metrics["total_return"] < 0)),
        "var_confidence": confidence, "var_loss": var, "cvar_loss": float(tail.mean()),
        "actual_percentile_rank": float(np.mean(metrics["total_return"] <= actual["total_return"])),
    }
