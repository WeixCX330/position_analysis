"""唯一任务入口：读MCP JSON → 划区间 → 回测/指标 → 分析 → HTML。"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np

from date_ranges.ranges import DATE_TYPES, resolve_period
from models.data import load_nav
from models.backtest import evaluate_period
from models.metrics import build_backtest_output
from analysis.analysis import analyze
from frontend.page import write_page


ROOT = Path(__file__).resolve().parent


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="单基金日频GBM历史回测；不调用旧项目")
    parser.add_argument("--json", dest="json_path", help="MCP响应JSON路径；-表示从标准输入读取")
    parser.add_argument("--prd-code", "--prdCode", "--fund-code", dest="prd_code",
                        help="产品编号，可含字母；默认读取同级data_json/fund_nav_<编号>.json，缺省001313")
    parser.add_argument("--date-type", "--dateType", nargs="+", default=["all"],
                        help="all 或 0..16，可传多个，例如 --date-type 0 1 4")
    parser.add_argument("--start-date", help="自定义起点 YYYY-MM-DD；与date-type互斥")
    parser.add_argument("--end-date", help="目标终点；默认JSON最后有效日期")
    parser.add_argument("--paths", type=int, default=10000)
    parser.add_argument("--train-window", type=int, default=252, help="普通档最多使用的起点前日收益数；成立以来固定使用前20条净值")
    parser.add_argument("--min-training", type=int, default=2,
                        help="普通档最低拟合日收益数，默认2；成立以来固定用前20条净值的19个收益")
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--risk-free-rate", type=float, default=0.0, help="年化小数，仅计算夏普")
    parser.add_argument("--confidence", type=float, default=.95)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results", help="运行目录的父目录")
    parser.add_argument("--llm", action="store_true", help="可选，向环境变量指定的服务发送数值摘要")
    args = parser.parse_args(argv)
    if args.paths < 1000 or args.min_training < 2 or args.train_window < args.min_training:
        parser.error("paths至少1000，min-training至少2，train-window不得小于min-training")
    if not 0 < args.confidence < 1 or not np.isfinite(args.risk_free_rate) or args.seed < 0:
        parser.error("置信度须在0到1之间，无风险利率须有限，seed不得为负")
    if args.start_date and args.date_type != ["all"]:
        parser.error("自定义start-date不能与date-type同时指定")
    if "all" in args.date_type and args.date_type != ["all"]:
        parser.error("all不能与其他date-type同时指定")
    selected = ["custom"] if args.start_date else list(DATE_TYPES) if args.date_type == ["all"] else list(dict.fromkeys(args.date_type))
    if any(code not in DATE_TYPES and code != "custom" for code in selected):
        parser.error("date-type仅支持0..16")
    try:
        json_path = args.json_path or str(ROOT.parent / "data_json" / f"fund_nav_{args.prd_code or '001313'}.json")
        json_input = json.load(sys.stdin) if json_path == "-" else json_path
        frame, source = load_nav(json_input)
        code_match = re.fullmatch(r"fund_nav_(.+)", Path(json_path).stem) if json_path != "-" else None
        code = args.prd_code or source["product_code"] or (code_match.group(1) if code_match else None)
        if not code:
            raise ValueError("MCP响应未带产品编号，请用--prdCode传入原请求中的prdCode")
        if args.prd_code and source["product_code"] and args.prd_code != source["product_code"]:
            raise ValueError("传入prdCode与JSON中的产品编号不一致")
        source["product_code"] = code
        config = {key: getattr(args, key) for key in
                  ("paths", "train_window", "min_training", "seed", "risk_free_rate", "confidence")}
        periods, all_metrics = [], {}
        for date_type in selected:
            meta, window = resolve_period(frame, date_type, args.end_date, args.start_date)
            period, raw_metrics = evaluate_period(frame, meta, window, config)
            periods.append(period)
            all_metrics.update({f"{date_type}_{name}": values for name, values in raw_metrics.items()})
            print(f"dateType={date_type} {period['label']}：" + ("回测完成" if period["available"] else period["reason"]), flush=True)
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        output = args.output_dir.expanduser().resolve() / f"{now:%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        output.mkdir(parents=True, exist_ok=False)
        cutoff = args.end_date or source["end_date"]
        frame.loc[frame["date"] <= cutoff].to_csv(output / "daily_returns.csv", index=False)
        np.savez_compressed(output / "path_metrics.npz", **all_metrics)
        result = json_safe({
            "schema_version": "1.3", "product_code": code, "product_name": source["product_name"],
            "generated_at": now.isoformat(),
            "data_as_of": str(frame.loc[frame["date"] <= cutoff].iloc[-1]["date"].date()),
            "source": source, "config": config, "method": "daily_normal_gbm",
            "periods": periods,
        })
        result["analysis"] = analyze(result, output, args.llm)
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        compact_path = output / "backtest_output.json"
        compact_path.write_text(json.dumps(build_backtest_output(result), ensure_ascii=False,
                                          indent=2, allow_nan=False) + "\n", encoding="utf-8")
        page = write_page(result, output)
        print(json.dumps({"result_dir": str(output), "report": str(page),
                          "backtest_output": str(compact_path),
                          "simulation_available": sum(p["available"] for p in periods),
                          "selected_periods": len(periods), "llm_used": result["analysis"]["llm_status"]["used"]},
                         ensure_ascii=False, indent=2))
        return output
    except (ValueError, FloatingPointError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
