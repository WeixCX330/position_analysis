#!/usr/bin/env python3
"""单基金日度极值风险：MCP JSON -> 日收益 -> POT/GPD -> VaR、ES、诊断与回测。

运行（在项目根目录）：
    python extreme_value_theory/pot.py --json data_json/fund_nav_001313.json
    python extreme_value_theory/pot.py /absolute/path/response.json --prdCode SMLC01
依赖：numpy、pandas、scipy、matplotlib（pip install numpy pandas scipy matplotlib）。
仅此文件包含全部实现；结果默认存入本文件旁的 results/<时间_产品编号>/。
至少 1001 条有效净值（1000 条收益），且日期跨度至少三个日历年。
不补交易日、不前向填充；相邻有效观测收益视为一个交易日收益，长缺口拒绝计算。
诊断图同时输出300 DPI PNG和矢量SVG；样式内置，不依赖外部skill或字体包。
"""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import warnings

import numpy as np
import pandas as pd
import scipy
from scipy.stats import binomtest, genpareto


MIN_RETURNS = 1000
MIN_EXCESSES = 30


def load_data(path):
    """校验 MCP 包装及两列数据；绝不使用 navUnit 代替累计净值。"""
    raw = path.read_bytes()
    obj = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(obj, dict) or obj.get("responseCode") != "000000":
        raise ValueError("MCP responseCode 必须为字符串 000000。")
    data = obj.get("data")
    if not isinstance(data, dict):
        raise ValueError("缺少 data 对象。")
    rows = data.get("list")
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) for r in rows):
        raise ValueError("data.list 必须是非空对象数组。")
    total = data.get("totalNum")
    if isinstance(total, bool) or not re.fullmatch(r"\d+", str(total)) or int(total) != len(rows):
        raise ValueError("totalNum 与 list 长度不符；请提供完整数据，不能只传一页。")
    field = ("navAccumulated" if any(r.get("navAccumulated") is not None for r in rows)
             else "per10000Income")
    records = []
    for i, row in enumerate(rows, 1):
        date, value = row.get("date"), row.get(field)
        if not isinstance(date, str) or not re.fullmatch(r"\d{8}", date):
            raise ValueError(f"第 {i} 条 date 必须是 YYYYMMDD 字符串。")
        try:
            date = pd.Timestamp(datetime.strptime(date, "%Y%m%d"))
            if isinstance(value, bool) or value is None:
                raise ValueError()
            value = float(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"第 {i} 条日期无效或 {field} 不是有效数值。") from exc
        if not np.isfinite(value) or (field == "navAccumulated" and value <= 0):
            raise ValueError(f"第 {i} 条累计净值须为有限正数。")
        if field == "per10000Income" and value <= -10000:
            raise ValueError(f"第 {i} 条每万份收益必须大于 -10000。")
        records.append((date, value))
    frame = pd.DataFrame(records, columns=["date", "input_value"])
    if frame.groupby("date")["input_value"].nunique().gt(1).any():
        raise ValueError("同一天存在冲突数值，无法确定日收益。")
    frame = frame.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if len(frame) < 2:
        raise ValueError("至少需要两个不同日期的有效数据才能计算收益。")
    if field == "per10000Income":
        # 输入是当日每万份收益，不对该数值做 pct_change；第一天没有前一日基准。
        frame["daily_return"] = frame.input_value / 10000.0
        frame.loc[0, "daily_return"] = np.nan
        with np.errstate(over="ignore", invalid="ignore"):
            frame["nav"] = np.exp(np.log1p(frame.daily_return.fillna(0)).cumsum())
        basis = "每万份收益/10000；假设当日收益全部再投资，生成起点为 1 的指数"
    else:
        frame["nav"] = frame.input_value
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            frame["daily_return"] = frame.nav / frame.nav.shift(1) - 1
        basis = "相邻累计净值之比减一；累计净值未必等于分红再投资总回报"
    frame["daily_loss"] = -frame.daily_return
    if not np.isfinite(frame.nav).all() or not np.isfinite(frame.daily_return.iloc[1:]).all():
        raise ValueError("收益率或重建净值溢出，检查输入量纲和异常数值。")
    source_info = obj.get("sourceInfo", {})
    if not isinstance(source_info, dict):
        source_info = {}
    source = {"json_path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
              "product_code": source_info.get("prdCode", data.get("prdCode")),
              "product_name": data.get("prdName"), "value_field": field,
              "return_basis": basis, "raw_rows": len(rows), "valid_nav_rows": len(frame),
              "identical_duplicate_rows_removed": len(rows) - len(frame),
              "source_info": source_info}
    return frame, source


def validate_length(frame):
    start, end = frame.date.iloc[0], frame.date.iloc[-1]
    gaps = frame.date.diff().dt.days.iloc[1:]
    checks = {"at_least_1000_daily_returns": len(frame) - 1 >= MIN_RETURNS,
              "at_least_three_calendar_years": end >= start + pd.DateOffset(years=3),
              "daily_frequency_plausible": float(gaps.median()) <= 3,
              "no_gap_over_14_calendar_days": int(gaps.max()) <= 14}
    return {"available": all(checks.values()), "checks": checks,
            "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
            "daily_return_count": len(frame) - 1, "minimum_daily_returns": MIN_RETURNS,
            "minimum_calendar_years": 3, "maximum_gap_days": int(gaps.max()),
            "median_gap_days": float(gaps.median()),
            "note": "同时满足三年跨度和1000条收益（至少1001条净值）。不把周/月数据或长缺口跨期收益当作日收益；14日为可配置前需人工核查的保守缺口上限。"}


def fit_pot(losses, q=0.95, minimum=MIN_EXCESSES):
    """严格大于线性插值分位数，位置固定零的 GPD 最大似然拟合。"""
    losses = np.asarray(losses, dtype=float)
    u = float(np.quantile(losses, q, method="linear"))
    y = losses[losses > u] - u
    if len(y) < minimum:
        raise ValueError(f"阈值 {q:g} 仅有 {len(y)} 个超额样本，最低需要 {minimum} 个；不自动降低阈值。")
    if np.unique(y).size < 3:
        raise ValueError("超额损失不同取值少于3个，无法可靠拟合连续 GPD。")
    # 标准化改善很小量级基金收益的数值条件；最后还原 beta 的原始单位。
    unit = float(y.mean())
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        xi, _, scaled_beta = genpareto.fit(y / unit, floc=0, method="MLE")
    beta = float(scaled_beta * unit)
    xi = float(xi)
    if not np.isfinite([xi, beta]).all() or beta <= 0 or np.any(1 + xi * y / beta <= 0):
        raise ValueError("GPD 拟合参数无效或违反支持集约束。")
    messages = []
    if len(y) < 50:
        messages.append("超阈值样本不足50个，结果仅供探索；置信区间可能很宽。")
    if u <= 0:
        messages.append("损失阈值不为正，尾部含上涨或零收益日；不能据此声称已观察到极端下跌。")
    if xi >= 1:
        messages.append("xi>=1，拟合尾部的均值发散，ES 不存在有限值。")
    if xi <= -0.5:
        messages.append("xi<=-0.5，有限端点附近的MLE可能不规则，参数及Bootstrap区间需谨慎解释。")
    return {"threshold_quantile": q, "threshold_loss": u, "sample_count": len(losses),
            "exceedance_count": len(y), "exceedance_frequency": len(y) / len(losses),
            "xi": xi, "beta": beta, "location": 0.0, "method": "GPD MLE; floc=0",
            "loss_upper_endpoint": u - beta / xi if xi < 0 else None,
            "warnings": messages}


def risk_at_level(fit, p):
    """单日原始损失分位数；小数单位；负 VaR 不截断。"""
    u, xi, beta, frequency = (fit[k] for k in ("threshold_loss", "xi", "beta", "exceedance_frequency"))
    if not 0 < 1 - p < frequency:
        raise ValueError(f"置信水平 {p:g} 必须满足 0 < 1-p < k/n={frequency:g}。")
    log_ratio = np.log(frequency / (1 - p))
    with np.errstate(over="ignore", invalid="ignore"):
        var = u + beta * log_ratio if abs(xi) < 1e-8 else u + beta / xi * np.expm1(xi * log_ratio)
    if not np.isfinite(var):
        raise ValueError("VaR 数值溢出，不能报告有限风险值。")
    es = (float(var) + beta - xi * u) / (1 - xi) if xi < 1 else None
    if es is not None and not np.isfinite(es):
        raise ValueError("ES 数值溢出。")
    return {"confidence_level": p, "horizon": "one_observed_trading_day", "var_loss": float(var),
            "es_loss": es, "es_status": "finite" if es is not None else "infinite_mean",
            "expected_exceedance_probability": 1 - p,
            "exceeds_100_percent_loss": bool(var > 1 or (es is not None and es > 1))}


def tail_probabilities(fit, levels=(0.03, 0.05, 0.10)):
    result = []
    for x in levels:
        if x <= fit["threshold_loss"]:
            result.append({"daily_loss_level": x, "probability": None,
                           "reason": "不高于拟合阈值，不能用尾部近似估计"})
        else:
            prob = fit["exceedance_frequency"] * genpareto.sf(
                x - fit["threshold_loss"], fit["xi"], loc=0, scale=fit["beta"])
            result.append({"daily_loss_level": x, "probability": float(prob)})
    return result


def diagnostics(losses, fit):
    mean_excess, stability = [], []
    for q in np.linspace(0.80, 0.975, 25):
        u = float(np.quantile(losses, q))
        y = losses[losses > u] - u
        mean_excess.append({"q": float(q), "threshold_loss": u, "count": len(y),
                            "mean_excess": float(y.mean()) if len(y) else None})
    for q in (0.90, 0.925, 0.95, 0.965, 0.975):
        try:
            row = fit_pot(losses, q, minimum=10)
            row["diagnostic_only"] = True
            stability.append(row)
        except (ValueError, RuntimeError, RuntimeWarning, FloatingPointError) as exc:
            stability.append({"threshold_quantile": q, "xi": None, "reason": str(exc)})
    y = np.sort(losses[losses > fit["threshold_loss"]] - fit["threshold_loss"])
    theory = genpareto.ppf((np.arange(1, len(y) + 1) - 0.5) / len(y),
                          fit["xi"], loc=0, scale=fit["beta"])
    return {"mean_excess": mean_excess, "threshold_stability": stability,
            "qq": {"theoretical_excess": theory.tolist(), "observed_excess": y.tolist()}}


def out_of_sample(losses, dates, q, levels):
    """冻结前80%拟合的阈值和参数；测试集从不参与训练。"""
    split = int(len(losses) * 0.8)
    train, test = losses[:split], losses[split:]
    base = {"train_count": len(train), "test_count": len(test),
            "train_start": str(dates[0])[:10], "train_end": str(dates[split - 1])[:10],
            "test_start": str(dates[split])[:10], "test_end": str(dates[-1])[:10],
            "method": "chronological_80_20_fixed_training_var",
            "note": "二项检验假定超越事件独立；未拒绝不代表模型正确，聚集统计仅为描述性诊断；未进行正式ES回测。"}
    try:
        fit = fit_pot(train, q)
        base.update(available=True, training_fit=fit, risk_backtests=[])
        for p in levels:
            risk = risk_at_level(fit, p)
            flags = test > risk["var_loss"]
            count = int(flags.sum())
            pvalue = float(binomtest(count, len(test), p=1 - p).pvalue)
            longest = current = 0
            for flag in flags:
                current = current + 1 if flag else 0
                longest = max(longest, current)
            base["risk_backtests"].append({**risk, "breach_count": count,
                "breach_rate": count / len(test), "expected_breach_count": len(test) * (1 - p),
                "binomial_two_sided_p_value": pvalue, "reject_at_5_percent": pvalue < 0.05,
                "adjacent_breach_pairs": int((flags[:-1] & flags[1:]).sum()),
                "longest_breach_run": longest,
                "breach_dates": [str(d)[:10] for d in dates[split:][flags]]})
    except (ValueError, RuntimeError, RuntimeWarning, FloatingPointError) as exc:
        base.update(available=False, reason=str(exc))
    return base


def bootstrap_intervals(losses, q, levels, repetitions, block_size, seed):
    """循环块Bootstrap；每次重新估计阈值和参数，保留短程时间依赖。"""
    base = {"method": "circular_block_bootstrap_reestimate_threshold_and_gpd", "seed": seed,
            "repetitions": repetitions, "block_size": block_size, "confidence_level": 0.95,
            "note": "近似95%百分位区间，不保证覆盖率；块长固定，未消除非平稳性；失败次数和无穷ES不隐去。"}
    if repetitions == 0:
        return {**base, "available": False, "reason": "用户关闭Bootstrap"}
    rng = np.random.default_rng(seed)
    values = {"xi": [], "beta": []}
    for p in levels:
        values[f"var_{p:g}"] = []
        values[f"es_{p:g}"] = []
    failures = {}
    for _ in range(repetitions):
        starts = rng.integers(0, len(losses), size=int(np.ceil(len(losses) / block_size)))
        indices = ((starts[:, None] + np.arange(block_size)) % len(losses)).ravel()[:len(losses)]
        try:
            fit = fit_pot(losses[indices], q)
            risks = [risk_at_level(fit, p) for p in levels]
            values["xi"].append(fit["xi"])
            values["beta"].append(fit["beta"])
            for p, risk in zip(levels, risks):
                values[f"var_{p:g}"].append(risk["var_loss"])
                values[f"es_{p:g}"].append(risk["es_loss"] if risk["es_loss"] is not None else np.inf)
        except (ValueError, RuntimeError, RuntimeWarning, FloatingPointError) as exc:
            key = str(exc)
            failures[key] = failures.get(key, 0) + 1
    valid = len(values["xi"])
    base.update(available=valid >= 30, successful_fits=valid, failed_fits=repetitions - valid,
                failure_reasons=failures, intervals={})
    if valid < 30:
        base["reason"] = "有效Bootstrap拟合少于30次，不报告区间；正式评估建议至少200次。"
        return base
    for key, observations in values.items():
        lower, upper = np.quantile(observations, [0.025, 0.975], method="inverted_cdf")
        base["intervals"][key] = {"lower": float(lower) if np.isfinite(lower) else None,
                                 "upper": float(upper) if np.isfinite(upper) else None,
                                 "upper_is_infinite": bool(np.isinf(upper)),
                                 "infinite_replicates": int(np.isinf(observations).sum())}
    if repetitions < 200 or valid / repetitions < 0.9:
        base["warning"] = "重复次数不足200或成功率低于90%，区间可能不稳定。"
    return base


def draw_diagnostics(result, frame, output):
    """只读取已有估计结果，绘制四联诊断图；不重新拟合或调整风险值。"""
    import os
    import tempfile
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "pot-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter, MaxNLocator, PercentFormatter

    output = Path(output)
    diag, oos = result["diagnostics"], result["out_of_sample"]
    fit = result["full_sample_fit"]
    blue, orange, navy, muted = "#0072B2", "#B34700", "#175777", "#526474"
    # 货币基金损失可能仅为万分之一量级，固定两位百分数会误显示成0.00%。
    loss_formatter = FuncFormatter(lambda value, _: f"{value * 100:.3g}%")
    styles = {"font.family": "DejaVu Sans", "font.size": 10,
              "text.color": "#172b3a", "axes.labelcolor": "#344657",
              "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
              "axes.titlepad": 26,
              "axes.spines.top": False, "axes.spines.right": False,
              "axes.edgecolor": "#87939f", "axes.linewidth": .7,
              "xtick.color": "#344657", "ytick.color": "#344657",
              "legend.frameon": False, "legend.fontsize": 8,
              "svg.fonttype": "path", "savefig.facecolor": "white"}
    with plt.rc_context(styles):
        fig, axes = plt.subplots(2, 2, figsize=(13.6, 9.2), layout="constrained")
        ax = axes[0, 0]
        rows = diag["mean_excess"]
        ax.plot([r["threshold_loss"] for r in rows],
                [r["mean_excess"] if r["mean_excess"] is not None else np.nan for r in rows],
                "o-", color=blue, markersize=3.5, linewidth=1.3, label="Empirical mean excess")
        ax.axvline(fit["threshold_loss"], color=orange, ls="--", lw=1.3,
                   label=f"Selected threshold q={fit['threshold_quantile']:.1%}")
        ax.set(title="A. Mean excess", xlabel="Daily loss threshold u (%)", ylabel="Mean excess loss (%)")
        ax.xaxis.set_major_formatter(loss_formatter)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value * 100:.3g}%"))
        ax.legend(loc="best")
        ax.text(0, 1.025, f"Full sample n={fit['sample_count']:,}; 25 candidate quantiles",
                color=muted, fontsize=8.5, transform=ax.transAxes)

        ax = axes[0, 1]
        rows = diag["threshold_stability"]
        ax.plot([r["threshold_quantile"] for r in rows],
                [r["xi"] if r["xi"] is not None else np.nan for r in rows],
                "s-", color=blue, markersize=4, linewidth=1.3, label="Candidate fits")
        ax.scatter([fit["threshold_quantile"]], [fit["xi"]], marker="D", s=42,
                   color=orange, edgecolor="white", linewidth=.6, zorder=4, label="Selected fit")
        ax.axhline(0, ls="--", color=muted, lw=.9, label="xi = 0 (exponential tail)")
        for row in rows:
            if row["xi"] is not None:
                ax.annotate(f"k={row['exceedance_count']}", (row["threshold_quantile"], row["xi"]),
                            xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8, color=muted)
        ax.set(title="B. Threshold sensitivity", xlabel="Loss threshold quantile (%)", ylabel="GPD shape xi (unitless)")
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=1))
        ax.set_xticks(sorted({r["threshold_quantile"] for r in rows} | {fit["threshold_quantile"]}))
        ax.margins(y=.28)
        ax.legend(loc="best")
        ax.text(0, 1.025, "Point estimates; k = exceedances; no confidence band",
                color=muted, fontsize=8.5, transform=ax.transAxes)

        ax = axes[1, 0]
        theory, observed = diag["qq"]["theoretical_excess"], diag["qq"]["observed_excess"]
        ax.scatter(theory, observed, s=20, color=blue, edgecolor="white", linewidth=.4,
                   label="Observed excesses", zorder=3)
        upper = max(max(theory), max(observed)) * 1.05
        ax.plot([0, upper], [0, upper], "--", color=orange, linewidth=1.4, label="y = x reference")
        ax.set(title="C. GPD Q-Q", xlabel="Theoretical excess loss (%)", ylabel="Observed excess loss (%)",
               xlim=(0, upper), ylim=(0, upper))
        # 相同单位、相同范围和等比例坐标，y=x才在视觉上真正为45度。
        ax.set_aspect("equal", adjustable="box")
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value * 100:.3g}%"))
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value * 100:.3g}%"))
        ax.legend(loc="upper left")
        ax.text(0, 1.025, f"Full-sample excesses k={fit['exceedance_count']}; identical axis scales",
                color=muted, fontsize=8.5, transform=ax.transAxes)

        ax = axes[1, 1]
        if oos["available"]:
            test = frame.iloc[1:].iloc[-oos["test_count"]:]
            risk = oos["risk_backtests"][0]
            breaches = test.daily_loss > risk["var_loss"]
            ax.scatter(test.date, test.daily_loss, s=12, color=blue, alpha=.7,
                       linewidths=0, label="Observed daily loss")
            ax.scatter(test.loc[breaches, "date"], test.loc[breaches, "daily_loss"], s=28,
                       color=orange, marker="^", edgecolor="white", linewidth=.4, zorder=4,
                       label=f"VaR exceedances (n={int(breaches.sum())})")
            ax.axhline(risk["var_loss"], color=navy, ls="--", lw=1.4,
                       label=f"Training-only VaR {risk['confidence_level']:.1%} = {risk['var_loss'] * 100:.3g}%")
            ax.axhline(0, color=muted, ls=":", lw=.7)
            ax.legend(loc="best")
            locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value * 100:.3g}%"))
            ax.text(0, 1.025, f"Holdout n={oos['test_count']:,}; frozen first-80% fit; no refitting",
                    color=muted, fontsize=8.5, transform=ax.transAxes)
        else:
            ax.text(0.5, 0.5, "Out-of-sample fit unavailable\nSee result.json for reason",
                    ha="center", va="center", color=muted, transform=ax.transAxes)
            ax.set(xticks=[], yticks=[])
        ax.set(title="D. Chronological holdout", xlabel="Observation date", ylabel="One-day loss (%)")
        for ax in axes.flat:
            ax.set_axisbelow(True)
            ax.grid(color="#e3e9ee", linewidth=.6)
            if ax is not axes[1, 1] or oos["available"]:
                ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        code = result.get("source", {}).get("product_code") or "unspecified"
        start, end = frame.date.iloc[0].strftime("%Y-%m-%d"), frame.date.iloc[-1].strftime("%Y-%m-%d")
        fig.suptitle(f"Fund {code} | POT / GPD diagnostics | {start} to {end}\n"
                     f"Daily loss = -return | n={fit['sample_count']:,} | selected q={fit['threshold_quantile']:.1%}",
                     fontsize=13)
        fig.savefig(output / "diagnostics.png", dpi=300, facecolor="white")
        fig.savefig(output / "diagnostics.svg", facecolor="white")
        plt.close(fig)
    metadata = {
        "source_sha256": result.get("source", {}).get("sha256"), "product_code": code,
        "start": start, "end": end, "full_sample_count": fit["sample_count"],
        "exceedance_count": fit["exceedance_count"], "selected_threshold_quantile": fit["threshold_quantile"],
        "holdout_plot_confidence": oos["risk_backtests"][0]["confidence_level"] if oos["available"] else None,
        "palette": {"observations": blue, "highlight": orange, "training_var": navy},
        "units": "Percent loss axes; xi is unitless; signs retained without clipping",
        "transformations": "Existing result arrays only; candidate thresholds connected without smoothing; no re-fitting",
        "uncertainty": "Threshold point estimates only; no confidence band; bootstrap intervals are in result.json",
        "missing": "Missing candidate estimates retained as line gaps; unavailable holdout labelled explicitly",
        "qq": "Same limits and equal aspect ratio; y=x is the 45-degree reference",
        "holdout": "All holdout observations shown without connecting or smoothing; exceedances highlighted above the first requested confidence VaR",
        "matplotlib": matplotlib.__version__, "png_dpi": 300, "size_inches": [13.6, 9.2],
    }
    (output / "diagnostics_meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(result, output):
    lines = ["# 单基金 POT 极值风险结果", "", f"状态：`{result['status']}`", "",
             "所有收益、损失、VaR、ES 均为小数：0.03 表示 3%。持有期限为一个观测交易日。", ""]
    if "error" in result:
        lines += [f"未计算原因：{result['error']}", ""]
    if "validation" in result:
        v = result["validation"]
        lines += [f"数据：{v['start']} 至 {v['end']}，{v['daily_return_count']} 条日收益。", "",
                  "最低要求：1000条有效日收益及三年日期跨度，另检查日频和长缺口。", ""]
    if "full_sample_fit" in result and "daily_risk" in result:
        f = result["full_sample_fit"]
        lines += [f"阈值分位 {f['threshold_quantile']:.1%}，阈值损失 {f['threshold_loss']:.6%}；",
                  f"超阈值 {f['exceedance_count']} 条，实际比例 {f['exceedance_frequency']:.4%}；xi={f['xi']:.6g}，beta={f['beta']:.6g}。", "",
                  "| 置信水平 | 单日损失 VaR | 单日损失 ES |", "| --- | --- | --- |"]
        for r in result["daily_risk"]:
            es = f"{r['es_loss']:.6%}" if r["es_loss"] is not None else "无穷（xi≥1）"
            lines.append(f"| {r['confidence_level']:.2%} | {r['var_loss']:.6%} | {es} |")
        lines += [""] + [f"注意：{message}" for message in f["warnings"]]
        oos = result.get("out_of_sample", {})
        if oos.get("available"):
            lines += ["", "## 样本外检验", ""]
            for row in oos["risk_backtests"]:
                lines.append(f"- {row['confidence_level']:.2%} VaR：测试期 {oos['test_count']} 天，"
                             f"超越 {row['breach_count']} 天（{row['breach_rate']:.2%}），"
                             f"二项检验 p={row['binomial_two_sided_p_value']:.4g}；"
                             f"最长连续超越 {row['longest_breach_run']} 天。")
            lines += ["", "二项检验未拒绝不代表模型已获验证；应结合聚集情况、阈值敏感性和置信区间判断。"]
        elif oos:
            lines += ["", f"样本外检验不可用：{oos.get('reason')}"]
        lines += ["", "全样本拟合描述截至数据末日的尾部风险；样本外检验独立使用前80%训练参数。",
                  "参数、VaR、ES 的95%循环块Bootstrap区间及失败次数详见 result.json。", "",
                  ("![POT诊断：均值超额、阈值敏感性、Q-Q及冻结训练VaR的样本外日损失](diagnostics.png)"
                   if (output / "diagnostics.png").exists() else "诊断图未生成，请查看错误原因。"), "",
                  "[下载矢量诊断图 SVG](diagnostics.svg) · [下载300 DPI PNG](diagnostics.png) · [绘图口径与来源](diagnostics_meta.json)", "",
                  "图中数据及变换可从 result.json 和 daily_returns.csv 复核；阈值敏感性图为点估计，无置信带。",
                  "A：均值超额随候选阈值变化，虚线为选定阈值；连线不代表平滑拟合。",
                  "B：不同阈值的xi点估计，k为超阈值样本数，菱形为实际选定的拟合。",
                  "C：等比例Q-Q图，横纵轴同范围，虚线为y=x；不删除或裁切尾部观测。",
                  "D：最后20%日期的全部日损失；虚线为仅用前80%训练数据拟合的固定VaR，三角形为超越。",
                  "若请求多个置信水平，D图展示参数列表中的第一个，其余结果见JSON和上方样本外检验。",
                  "亏损为正、盈利为负，未对VaR或日损失取绝对值；纵轴按数据自动定范围，不强制从零开始。",
                  "绘图样式内置于pot.py，无需额外skill或Python包。这里采用一般科研图表样式，不表示满足某个期刊投稿规范。", ""]
    lines += ["## 解释边界", ""] + [f"- {s}" for s in result["limitations"]]
    lines += ["", "## 方法来源", "", "实现依据：用户提供的《极值理论-POT方法.md》。",
              "[SciPy GPD](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.genpareto.html)；",
              "[SciPy 二项检验](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html)。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("json_path", nargs="?", type=Path, help="MCP JSON 文件路径")
    parser.add_argument("--json", dest="json_option", type=Path, help="同 json_path，二选一")
    parser.add_argument("--prdCode", "--prd-code", dest="product_code")
    parser.add_argument("--threshold", type=float, default=0.95, help="损失阈值分位，默认0.95")
    parser.add_argument("--confidence", type=float, nargs="+", default=[0.99], help="目标置信水平，默认0.99")
    parser.add_argument("--bootstrap", type=int, default=200, help="循环块Bootstrap次数，默认200；0关闭")
    parser.add_argument("--block-size", type=int, default=20, help="Bootstrap块长，默认20条日收益")
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "results")
    args = parser.parse_args(argv)
    if bool(args.json_path) == bool(args.json_option):
        parser.error("必须指定一个 JSON 文件路径（位置参数或 --json）。")
    if (not 0.8 <= args.threshold <= 0.99 or not all(0 < p < 1 for p in args.confidence)
            or args.bootstrap < 0 or not 1 <= args.block_size <= MIN_RETURNS or args.seed < 0):
        parser.error("threshold须在[0.8,0.99]，confidence在(0,1)，bootstrap非负，块长1..1000，seed非负。")
    path = (args.json_path or args.json_option).expanduser().resolve()
    label = re.sub(r"[^A-Za-z0-9_-]", "_", args.product_code or path.stem)
    output = args.output_dir.expanduser().resolve() / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{label}"
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "initializing", "created_at": datetime.now().astimezone().isoformat(),
              "units": {"frequency": "daily_observation", "holding_period": "one_observed_trading_day",
                        "return_and_loss": "decimal; 0.03 = 3%; daily_loss = -daily_return",
                        "xi": "dimensionless", "beta_and_threshold": "decimal_loss"},
              "config": {"threshold_quantile": args.threshold, "confidence_levels": args.confidence,
                         "bootstrap_repetitions": args.bootstrap, "block_size": args.block_size, "seed": args.seed},
              "versions": {"python": sys.version.split()[0], "numpy": np.__version__,
                           "pandas": pd.__version__, "scipy": scipy.__version__},
              "limitations": ["日度VaR/ES不是月度累计收益或最大回撤，也不是最大可能亏损。",
                  "全样本拟合使用所有已知历史，不能冒充各历史时点的预测；样本外检验仅使用训练期拟合参数。",
                  "不填补日期缺口，不调整分红或拆分；累计净值不一定是分红再投资总回报，应核对数据口径。",
                  "GPD是高阈值渐近近似；阈值、极值数量、结构变化及时间依赖会影响可靠性；拟合成功不是模型通过验证。",
                  "Bootstrap采用固定20条观测的循环块（可用参数调整），置信区间仍是近似；二项检验未校正时间依赖。",
                  "原始收益包含上涨日对应的负损失；负VaR/ES不截零，不代表产品没有未来下跌风险。",
                  "GPD外推可能超过单日100%损失的经济边界；此时报告异常标志而不截断或强行解释。",
                  "货币基金若仅提供每万份收益，按收益/10000处理，假设当日收益可再投资；不对每万份收益做涨跌幅。",
                  "单基金VaR不能直接相加或按权重求和得到组合VaR。"]}
    exit_code = 0
    try:
        frame, source = load_data(path)
        if args.product_code:
            source["product_code"] = args.product_code
        if not source["product_code"]:
            match = re.fullmatch(r"fund_nav_([A-Za-z0-9]+)", path.stem)
            source["product_code"] = match.group(1) if match else None
        result["source"] = source
        result["validation"] = validate_length(frame)
        frame.to_csv(output / "daily_returns.csv", index=False, date_format="%Y-%m-%d")
        if not result["validation"]["available"]:
            failed = [k for k, v in result["validation"]["checks"].items() if not v]
            result.update(status="data_validation_failed", error="数据未达到计算要求：" + ", ".join(failed))
            exit_code = 2
        else:
            losses = frame.daily_loss.iloc[1:].to_numpy()
            fit = fit_pot(losses, args.threshold)
            result["full_sample_fit"] = fit
            result["daily_risk"] = [risk_at_level(fit, p) for p in args.confidence]
            result["tail_probabilities"] = tail_probabilities(fit)
            result["diagnostics"] = diagnostics(losses, fit)
            result["out_of_sample"] = out_of_sample(losses, frame.date.iloc[1:].to_numpy(), args.threshold, args.confidence)
            print(f"已拟合GPD，正在执行 {args.bootstrap} 次循环块Bootstrap…", file=sys.stderr, flush=True)
            result["bootstrap"] = bootstrap_intervals(losses, args.threshold, args.confidence,
                                                       args.bootstrap, args.block_size, args.seed)
            result["status"] = "estimated_requires_diagnostic_review"
            draw_diagnostics(result, frame, output)
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, RuntimeWarning, FloatingPointError) as exc:
        result.update(status="calculation_unavailable", error=str(exc))
        exit_code = 2
    write_report(result, output)
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "result_json": str(output / "result.json"),
                      "report": str(output / "report.md"), "error": result.get("error")}, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
