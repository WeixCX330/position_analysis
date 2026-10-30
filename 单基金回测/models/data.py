"""MCP JSON读取与一次性CSV转换；计算只使用日期及累计净值/每万份收益。"""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd


def load_nav(json_source):
    if isinstance(json_source, dict):
        payload, filename = json_source, None
        raw_bytes = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    else:
        path = Path(json_source).expanduser().resolve()
        raw_bytes, filename = path.read_bytes(), str(path)
        payload = json.loads(raw_bytes.decode("utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("responseCode") != "000000":
        raise ValueError("MCP返回失败或缺少responseCode=000000，不能进入回测")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise ValueError("MCP返回必须包含data.list数组")
    rows = data["list"]
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError("data.list为空或含非对象记录")
    total = data.get("totalNum")
    if isinstance(total, bool) or not str(total).isdigit() or int(total) != len(rows):
        raise ValueError("totalNum与list条数不一致；请取齐分页数据后再回测")
    column = "navAccumulated" if any(r.get("navAccumulated") is not None for r in rows) else "per10000Income"
    if any(isinstance(r.get(column), bool) or not isinstance(r.get(column), (str, int, float)) for r in rows):
        raise ValueError(f"每条记录必须提供数值或数字字符串{column}，不能用navUnit替代")
    frame = pd.DataFrame({"date": [str(r.get("date", "")) for r in rows],
                          "value": [r.get(column) for r in rows]})
    if not frame["date"].str.fullmatch(r"\d{8}").all():
        raise ValueError("date必须为YYYYMMDD格式，例如20261028")
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    if frame["date"].isna().any() or not np.isfinite(frame["value"]).all():
        raise ValueError(f"日期或{column}无效，不能用navUnit替代或补零")
    if (frame["value"] <= (0 if column == "navAccumulated" else -10000)).any():
        raise ValueError("累计净值须大于0，每万份收益须大于-10000")
    if (frame.groupby("date")["value"].nunique() > 1).any():
        raise ValueError("同一日期存在不同数值，不能自行选择一条")
    frame = frame.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if len(frame) < 2:
        raise ValueError("至少需要两条有效日期记录")
    if column == "per10000Income":
        levels = (1 + frame["value"] / 10000).cumprod()
        frame["nav"] = levels / levels.iloc[0]
        basis = "per_10000_income_reinvestment_index"
    else:
        frame["nav"], basis = frame["value"], "reported_accumulated_nav"
    if not np.isfinite(frame["nav"]).all() or (frame["nav"] <= 0).any():
        raise ValueError("收益指数构造出现溢出或非正值")
    frame = frame.drop(columns="value")
    frame["daily_return"] = frame["nav"].pct_change(fill_method=None)
    frame["daily_log_return"] = np.log(frame["nav"] / frame["nav"].shift())
    info = payload.get("sourceInfo", {})
    if not isinstance(info, dict):
        raise ValueError("sourceInfo如存在必须为对象")
    product_code = data.get("prdCode") or info.get("prdCode")
    if product_code is not None and not isinstance(product_code, str):
        raise ValueError("prdCode须为字符串，避免丢失前导零")
    if data.get("prdName") is not None and not isinstance(data["prdName"], str):
        raise ValueError("prdName须为字符串")
    source = {
        "format": "mcp_json", "file": filename, "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "product_name": data.get("prdName"), "product_code": product_code,
        "value_field": column, "nav_basis": basis,
        "input_rows": len(rows), "valid_rows": len(frame),
        "duplicate_rows_removed": len(rows) - len(frame),
        "start_date": frame.iloc[0]["date"].date().isoformat(),
        "end_date": frame.iloc[-1]["date"].date().isoformat(),
        "conversion_info": info,
    }
    return frame, source


def convert_csvs(project_root=None):
    """一次性生成四份本地MCP样例；运行回测时不调用此函数。"""
    tool_dir = Path(__file__).resolve().parents[1]
    root = Path(project_root) if project_root else tool_dir.parent
    output = root / "data_json"
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for code in ("001313", "002692", "015723", "150005"):
        csv_path = root / f"data/cache/fund_nav_{code}.csv"
        raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False).sort_values("date")
        original_count = len(raw)
        profile = json.loads((root / f"data/reference/fund_{code}_profile.json").read_text(encoding="utf-8"))
        money = code == "150005"
        note = "累计净值及单位净值从原CSV直接转换，回测仅读取累计净值。"
        if money:
            # 该源2004—2008有缺口/重叠；只导出已核验连续的2009年起区间。
            raw = raw.loc[raw["date"] >= "2009-01-01"].copy()
            starts = pd.to_datetime(raw["period_start_date"], errors="raise").reset_index(drop=True)
            dates = pd.to_datetime(raw["date"], errors="raise").reset_index(drop=True)
            if (starts > dates).any() or not ((starts.iloc[1:].reset_index(drop=True) - dates.iloc[:-1].reset_index(drop=True)).dt.days == 1).all():
                raise ValueError("150005的收益期间存在缺口或重叠，不能构造连续收益序列")
            note = "货币基金保留每万份收益；2004—2008年存在期间缺口/重叠，仅导出2009年起连续记录。模型内部逐期复投构造收益指数，不将每万份收益冒充累计净值。"
        records = []
        for row in raw.to_dict("records"):
            item = {"date": pd.Timestamp(row["date"]).strftime("%Y%m%d")}
            if money:
                item["per10000Income"] = row["per_10000_income"]
            else:
                item.update(navAccumulated=row["accumulated_nav"], navUnit=row["unit_nav"])
            records.append(item)
        payload = {
            "data": {"prdName": profile["prd_name"], "totalNum": len(records), "list": records},
            "responseCode": "000000", "responseMsg": "success",
            "Thread": hashlib.sha256(csv_path.read_bytes()).hexdigest()[:32],
            "sourceInfo": {"mock": True, "prdCode": code, "sourceFile": str(csv_path),
                           "originalRows": original_count, "exportedRows": len(records),
                           "excludedRows": original_count - len(records), "note": note},
        }
        path = output / f"fund_nav_{code}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


if __name__ == "__main__":
    for generated in convert_csvs():
        print(generated)
