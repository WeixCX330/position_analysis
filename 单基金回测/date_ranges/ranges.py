"""dateType 的日期划分；仅此文件负责日期规则。"""
import pandas as pd


# 用户提供的编号实际为 0..16，共 17 档；11/12 补齐原文缺失的编号。
DATE_TYPES = {
    "0": ("1天", "days", 1), "1": ("1周", "days", 7),
    "2": ("1个月", "months", 1), "3": ("3个月", "months", 3),
    "4": ("1年", "years", 1), "5": ("半年", "months", 6),
    "6": ("3年", "years", 3), "7": ("2年", "years", 2),
    "8": ("4年", "years", 4), "9": ("成立以来", "since", 0),
    "10": ("5年", "years", 5), "11": ("今年以来", "ytd", 0),
    "12": ("当月以来", "mtd", 0), "13": ("6年", "years", 6),
    "14": ("10年", "years", 10), "15": ("2个月", "months", 2),
    "16": ("4个月", "months", 4),
}
WARMUP_NAV_COUNT = 20


def resolve_period(frame, date_type, end_date=None, start_date=None):
    code = str(date_type)
    if start_date is None and code not in DATE_TYPES:
        raise ValueError(f"未知 dateType: {code}")
    cutoff = pd.Timestamp(end_date).normalize() if end_date else frame.iloc[-1]["date"]
    before_end = frame.loc[frame["date"] <= cutoff]
    if before_end.empty or (cutoff - before_end.iloc[-1]["date"]).days > 7:
        raise ValueError(f"{cutoff.date()} 附近没有有效数据；JSON不会自动补到今天")
    end = before_end.iloc[-1]["date"]
    if start_date:
        label, target, basis = "自定义区间", pd.Timestamp(start_date).normalize(), "custom"
    else:
        label, unit, amount = DATE_TYPES[code]
        basis = "calendar_offset"
        if unit == "since":
            target, basis = before_end.iloc[0]["date"], "initial_20_nav"
            if len(before_end) > WARMUP_NAV_COUNT:
                target = before_end.iloc[WARMUP_NAV_COUNT - 1]["date"]
        elif unit == "ytd":
            target = pd.Timestamp(year=cutoff.year, month=1, day=1) - pd.Timedelta(days=1)
        elif unit == "mtd":
            target = cutoff.replace(day=1) - pd.Timedelta(days=1)
        else:
            target = cutoff - pd.DateOffset(**{unit: amount})
    meta = {
        "date_type": code, "label": label, "requested_start": target.date().isoformat(),
        "requested_end": cutoff.date().isoformat(), "start_basis": basis,
        "historical_available": False, "available": False,
    }
    if basis == "initial_20_nav":
        meta.update(data_start=before_end.iloc[0]["date"].date().isoformat(),
                    warmup_nav_count=WARMUP_NAV_COUNT)
        if len(before_end) <= WARMUP_NAV_COUNT:
            meta["reason"] = (f"成立以来需前{WARMUP_NAV_COUNT}条净值训练，并至少再有1条用于回测"
                              f"（至少{WARMUP_NAV_COUNT + 1}条）；截至终点仅有{len(before_end)}条")
            return meta, frame.iloc[:0]
    if target >= end:
        meta["reason"] = "起点不早于有效终点，没有完整收益区间"
        return meta, frame.iloc[:0]
    candidates = frame.loc[frame["date"] <= target]
    if candidates.empty or (target - candidates.iloc[-1]["date"]).days > 14:
        meta["reason"] = "目标起点附近历史净值不足，不能缩短后冒充该期限"
        return meta, frame.iloc[:0]
    start = candidates.iloc[-1]["date"]
    window = before_end.loc[before_end["date"] >= start].copy()
    if window["date"].diff().dt.days.max() > 14:
        meta["reason"] = "历史区间内存在超过14个自然日的观测缺口"
        return meta, frame.iloc[:0]
    meta.update(start=start.date().isoformat(), end=end.date().isoformat(),
                historical_available=True, observation_count=len(window), steps=len(window) - 1,
                elapsed_years=(end - start).days / 365.2425)
    return meta, window
