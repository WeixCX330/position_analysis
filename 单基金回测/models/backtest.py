"""日频GBM：普通档起点前估计，成立以来以前20条净值训练，之后模拟。"""
import numpy as np
import pandas as pd

from models.metrics import METRICS, path_metrics, summarize
from date_ranges.ranges import WARMUP_NAV_COUNT


def fit_model(frame, origin, train_window=252, min_training=2, warmup=False):
    if warmup:
        history = frame.loc[frame["date"] <= pd.Timestamp(origin)]
        if len(history) != WARMUP_NAV_COUNT:
            raise ValueError(f"成立以来的训练区间必须恰好包含前{WARMUP_NAV_COUNT}条净值")
        if history["date"].diff().dt.days.max() > 14:
            raise ValueError("前20条训练净值存在超过14个自然日的缺口")
        # 第20条净值是起点。包含截至该日已知的收益，绝不使用第21条以后的收益。
        sample = history.iloc[1:][["date", "daily_log_return"]].dropna()
        if len(sample) != WARMUP_NAV_COUNT - 1:
            raise ValueError("前20条净值未能产生19个有效日收益")
        mode, scope = "initial_20_nav_out_of_sample", "前20条净值内"
        min_training = WARMUP_NAV_COUNT - 1
    else:
        # 其他档严格排除起点当日和起点后的收益。
        sample = frame.loc[frame["date"] < pd.Timestamp(origin), ["date", "daily_log_return"]]
        sample = sample.dropna().tail(train_window)
        mode, scope = "pre_origin_out_of_sample", "起点前"
    if len(sample) < min_training:
        raise ValueError(f"{scope}仅{len(sample)}个日收益，少于最低{min_training}个")
    mean, std = float(sample["daily_log_return"].mean()), float(sample["daily_log_return"].std(ddof=1))
    if not np.isfinite(std) or std <= 0:
        raise ValueError(f"{scope}日收益波动为零或无效，不能拟合GBM")
    fit = {
        "calibration_mode": mode,
        "daily_log_mean": mean, "daily_log_std": std,
        "annual_log_drift": mean * 252, "annual_volatility": std * np.sqrt(252),
        "annual_gbm_mu": mean * 252 + 0.5 * std * std * 252,
        "training_start": sample.iloc[0]["date"].date().isoformat(),
        "training_end": sample.iloc[-1]["date"].date().isoformat(),
        "training_observations": len(sample),
    }
    if warmup:
        fit.update(training_nav_count=WARMUP_NAV_COUNT,
                   training_nav_start=history.iloc[0]["date"].date().isoformat())
    return fit


def simulate(start_nav, steps, fit, path_count, seed, years, risk_free_rate=0.0):
    rng = np.random.default_rng(seed)
    chunks = {key: [] for key in METRICS}
    indices = np.unique(np.linspace(0, steps, min(121, steps + 1)).astype(int))
    samples = []
    # 不在内存中累计所有完整路径；一批处理完只留下逐路径指标。
    for offset in range(0, path_count, 1000):
        count = min(1000, path_count - offset)
        shocks = rng.normal(fit["daily_log_mean"], fit["daily_log_std"], (count, steps))
        with np.errstate(over="raise", invalid="raise"):
            values = start_nav * np.exp(np.cumsum(shocks, axis=1))
        paths = np.concatenate((np.full((count, 1), start_nav), values), axis=1)
        computed = path_metrics(paths, years, risk_free_rate)
        for key in chunks:
            chunks[key].append(computed[key])
        if offset == 0:
            samples = paths[:10, indices].tolist()
    return {key: np.concatenate(value) for key, value in chunks.items()}, indices, samples


def evaluate_period(frame, meta, window, config):
    result = dict(meta)
    if not meta["historical_available"]:
        return result, {}
    years = meta["elapsed_years"]
    actual_values = path_metrics(window["nav"].to_numpy()[None, :], years, config["risk_free_rate"])
    result["actual"] = {key: float(value[0]) if np.isfinite(value[0]) else None
                        for key, value in actual_values.items()}
    notes = []
    if years < 1:
        notes.append("不足一年区间的年化收益只是数学换算，不代表全年收益；越短越不稳定。")
    warmup = meta["start_basis"] == "initial_20_nav"
    if warmup:
        notes.append("成立以来以前20条有效净值产生的19个日收益估参，以第20条净值作为模拟起点，从第21条开始评价；首段训练期不计入本档真实回测收益。")
    if meta["steps"] < 2:
        notes.append("仅一个日收益，真实及模拟年化波动率、夏普均不可计算。")
    result["notes"] = notes
    plot_indices = np.unique(np.linspace(0, len(window) - 1, min(121, len(window))).astype(int))
    result["chart_data"] = {"dates": window.iloc[plot_indices]["date"].dt.strftime("%Y-%m-%d").tolist(),
                            "actual_nav": window.iloc[plot_indices]["nav"].tolist(), "sample_paths": []}
    try:
        fit = fit_model(frame, meta["start"], config["train_window"], config["min_training"],
                        warmup=warmup)
    except ValueError as exc:
        result["reason"] = str(exc)
        return result, {}
    seed = config["seed"] + (int(meta["date_type"]) + 1) * 100003 if meta["date_type"].isdigit() else config["seed"] + 999983
    metrics, indices, samples = simulate(float(window.iloc[0]["nav"]), meta["steps"], fit,
                                        config["paths"], seed, years, config["risk_free_rate"])
    result.update(available=True, fit=fit, path_count=config["paths"], simulation_seed=seed,
                  simulation=summarize(metrics, result["actual"], config["confidence"]))
    result["chart_data"] = {"dates": window.iloc[indices]["date"].dt.strftime("%Y-%m-%d").tolist(),
                            "actual_nav": window.iloc[indices]["nav"].tolist(), "sample_paths": samples}
    if fit["training_observations"] < 60:
        result["notes"].append(f"仅用{fit['training_observations']}个日收益拟合，只满足数值计算条件；样本很少，模拟分位、VaR/CVaR等结果不稳定。")
    elif fit["training_observations"] < 252:
        result["notes"].append("拟合样本不足252个日收益，参数估计仅使用实际可用样本。")
    return result, metrics
