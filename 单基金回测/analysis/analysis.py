"""结果画图、确定性分析、可选的大模型分析，集中在这一个文件。"""
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

from models.metrics import METRICS


def pct(value):
    return "不可用" if value is None else f"{value:.2%}"


def draw_charts(result, output_dir):
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "single-fund-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    available = [p for p in result["periods"] if p["available"]]
    if not available:
        return None
    period = next((p for p in available if p["date_type"] == "4"), available[0])
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, key in zip(axes.flat, METRICS):
        dist = period["simulation"]["metric_distributions"][key]
        ax.set_title(key.replace("_", " "))
        if not dist["available"]:
            ax.text(.5, .5, "Insufficient daily\nobservations", ha="center", fontsize=10, transform=ax.transAxes)
            continue
        edges, counts = dist["histogram"]["edges"], dist["histogram"]["counts"]
        ax.stairs(counts, edges, fill=True, color="#5a80a0", alpha=.75)
        for q in ("p05", "p50", "p95"):
            ax.axvline(dist["percentiles"][q], color="#267a70", alpha=.8, lw=1)
        actual = period["actual"][key]
        if actual is not None:
            ax.axvline(actual, color="#d05c37", lw=1.6, label="Actual")
            ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=.2)
        if key != "sharpe_ratio":
            ax.xaxis.set_major_formatter(FuncFormatter(
                lambda value, _: f"{value * 100:.1e}%" if abs(value) >= 1e4 else f"{value * 100:.0f}%"))
            if max(abs(edges[0]), abs(edges[-1])) >= 1e4:
                ax.xaxis.set_major_locator(MaxNLocator(nbins=3))
    mode = "20 NAV warmup / Out-of-sample" if period["fit"]["calibration_mode"] == "initial_20_nav_out_of_sample" else "Out-of-sample"
    fig.suptitle(f"Fund {result['product_code']} | {period['start']} - {period['end']} | Daily GBM | {mode}")
    fig.tight_layout()
    path = Path(output_dir) / "charts.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path.name


def deterministic_analysis(result):
    source = result["source"]
    money = source["nav_basis"] == "per_10000_income_reinvestment_index"
    input_note = ("输入为日期和每万份收益，已逐期复投为内部收益指数，图中水平不是披露累计净值。"
                  if money else "输入为日期和累计净值；未读取navUnit作为计算依据。")
    lines = [f"# {result['product_code']} {result.get('product_name') or ''} 单基金历史回测", "",
             f"数据截止日：{result['data_as_of']}；模拟：日频正态GBM，每档{result['config']['paths']:,}条路径。", "",
             input_note, source.get("conversion_info", {}).get("note", ""), "",
             "成立以来档以前20条净值训练，以第20条净值为起点模拟之后区间；其他档只用起点前收益估计。均不使用模拟起点后的收益估参。模拟的是已发生的历史区间，不是未来预测或客户账户收益。", "",
             "| 区间 | 实际起止日 | 真实累计收益 | 真实最大回撤 | 模拟P5 / P50 / P95 | 模拟亏损频率 | VaR / CVaR |",
             "| :--- | :--- | ---: | ---: | :--- | ---: | :--- |"]
    for period in result["periods"]:
        if not period["historical_available"]:
            lines.append(f"| {period['label']} | {period['reason']} | — | — | — | — | — |")
            continue
        actual = period["actual"]
        label = period["label"] + ("（前20条训练）" if period.get("fit", {}).get("calibration_mode") == "initial_20_nav_out_of_sample" else "")
        cells = [label, f"{period['start']}—{period['end']}", pct(actual["total_return"]),
                 pct(actual["maximum_drawdown"])]
        if period["available"]:
            sim = period["simulation"]
            q = sim["metric_distributions"]["total_return"]["percentiles"]
            cells += [" / ".join(pct(q[k]) for k in ("p05", "p50", "p95")),
                      pct(sim["loss_frequency"]), f"{pct(sim['var_loss'])} / {pct(sim['cvar_loss'])}"]
        else:
            cells += [period["reason"], "—", "—"]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## 分析要点", ""]
    for p in result["periods"]:
        if not p["available"]:
            continue
        sim = p["simulation"]
        rank = sim["actual_percentile_rank"]
        position = "低于模型5%分位" if rank < .05 else "高于模型95%分位" if rank > .95 else "位于模型中间90%范围内"
        if p["fit"]["calibration_mode"] == "initial_20_nav_out_of_sample":
            lines.append(f"- {p['label']}：数据始于{p['data_start']}，前20条净值产生19个日收益用于估参；"
                         f"实际回测从第20条净值（{p['start']}）到{p['end']}。真实累计收益{pct(p['actual']['total_return'])}，"
                         f"{position}（模拟百分位{pct(rank)}）。首段训练期不计入这项回测收益，单次对照不能代表长期预测准确率。")
            continue
        lines.append(f"- {p['label']}：真实累计收益{pct(p['actual']['total_return'])}，{position}（模拟百分位{pct(rank)}）。"
                     "这只是一次固定起点对照，不能当作长期模型准确率。")
    lines += ["", "## 口径与限制", "",
              "- VaR/CVaR 的损失变量是负的终点累计收益；所有模拟路径盈利时两者可以为负，不截断为零。",
              "- 最大回撤来自完整日频路径，亏损频率只看终点，二者不能互相替代。",
              "- 不足两个日收益时，波动率和夏普不可计算；短区间年化收益容易放大，不代表未来年收益。",
              "- 普通档默认最低拟合样本为2个日收益；成立以来固定以前20条净值的19个收益训练。少量样本的GBM参数和风险分布不稳定。",
              "- 每一步对应JSON中的一个有效观测间隔；节假日合并期间不是额外补造交易日。",
              "- 普通产品仅读取date与navAccumulated；货币基金读取date与per10000Income并复投，不把每万份收益当价格。",
              "- 累计净值与严格分红再投复权净值未必同口径；来源口径仍需核对。",
              "- dateType=9按有效净值条数预留前20条训练，不按自然日计数。第20条作为起点，从第21条开始评价，至少需要21条记录。",
              "- 无产品基准、客户交易和底层穿透数据，不输出跑输基准或客户亏损原因结论。"]
    return "\n".join(lines) + "\n"


def call_llm(result):
    key, base, model = (os.environ.get(name) for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"))
    if not all((key, base, model)):
        return None, {"used": False, "reason": "缺少LLM_API_KEY、LLM_BASE_URL或LLM_MODEL，使用本地分析"}
    if not base.startswith("https://"):
        return None, {"used": False, "reason": "LLM_BASE_URL须使用HTTPS，使用本地分析"}
    # 不发送原始JSON、完整路径和直方图，只发送已有数值摘要。
    compact = []
    for p in result["periods"]:
        item = {k: v for k, v in p.items() if k not in ("chart_data", "simulation")}
        if p["available"]:
            sim = p["simulation"]
            item["simulation"] = {k: v for k, v in sim.items() if k != "metric_distributions"}
            item["simulation"]["percentiles"] = {
                k: d.get("percentiles") for k, d in sim["metric_distributions"].items()}
        compact.append(item)
    body = {"model": model, "temperature": .2, "max_tokens": 1800, "messages": [
        {"role": "system", "content": "你是基金历史回测分析师。只解释给定数值，不计算或编造新数字。先报告真实历史结果，再解释模拟风险和模型限制。fit.calibration_mode为initial_20_nav_out_of_sample时，成立以来档以前20条净值产生的19个收益训练，第20条作为起点，随后收益不参与估参；报告start/end之间的真实结果，不能称从第一条数据起的完整累计收益。pre_origin_out_of_sample是其他档起点前估参的样本外对照。两者都不是未来预测、客户盈亏或行业因果，单次回测不能证明长期预测准确。不可用字段不作推断；亏损路径频率不是校准概率；短期年化不作收益承诺。用简洁中文Markdown写关键发现和限制。"},
        {"role": "user", "content": json.dumps({"product_code": result["product_code"],
            "data_as_of": result["data_as_of"], "periods": compact}, ensure_ascii=False, allow_nan=False)},
    ]}
    request = urllib.request.Request(base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        choice = payload["choices"][0]
        content = choice["message"]["content"].strip()
        if not content or choice.get("finish_reason") == "length":
            raise ValueError("模型正文为空或被截断")
        return content, {"used": True, "model": model}
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, TypeError, ValueError) as exc:
        return None, {"used": False, "reason": f"调用失败（{type(exc).__name__}），使用本地分析"}


def analyze(result, output_dir, use_llm=False):
    chart_file = draw_charts(result, output_dir)
    text = deterministic_analysis(result)
    status = {"used": False, "reason": "未启用大模型，使用本地分析"}
    if use_llm:
        generated, status = call_llm(result)
        if generated:
            text += "\n## 大模型解读\n\n" + generated + "\n"
    (Path(output_dir) / "analysis.md").write_text(text, encoding="utf-8")
    return {"text": text, "llm_status": status, "chart_file": chart_file}
