from pathlib import Path
import sys
from statistics import NormalDist
import io
import json

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from date_ranges.ranges import DATE_TYPES, resolve_period
from models.data import load_nav
from models.backtest import fit_model, simulate, evaluate_period
from models.metrics import path_metrics, summarize
from analysis.analysis import call_llm


def nav_frame(start="2010-01-01", end="2026-09-10"):
    dates = pd.bdate_range(start, end)
    nav = np.exp(np.cumsum(np.random.default_rng(5).normal(.0001, .01, len(dates))))
    frame = pd.DataFrame({"date": dates, "nav": nav})
    frame["daily_return"] = frame["nav"].pct_change()
    frame["daily_log_return"] = np.log(frame["nav"] / frame["nav"].shift())
    return frame


def mcp_payload(rows):
    return {"data": {"prdName": "测试产品", "totalNum": len(rows), "list": rows},
            "responseCode": "000000", "responseMsg": "success", "Thread": "local-test"}


def test_all_date_types_and_calendar_baselines():
    frame = nav_frame()
    assert set(DATE_TYPES) == {str(n) for n in range(17)}
    for code in DATE_TYPES:
        p, _ = resolve_period(frame, code)
        assert p["historical_available"], (code, p)
    assert resolve_period(frame, "11")[0]["start"] == "2025-12-31"
    assert resolve_period(frame, "12")[0]["start"] == "2026-08-31"
    assert resolve_period(frame, "0")[0]["start"] == "2026-09-09"
    assert resolve_period(frame, "4", "2024-02-29")[0]["requested_start"] == "2023-02-28"


def test_weekend_day_and_no_shortening_long_history():
    frame = nav_frame("2023-01-01", "2024-03-04")
    assert resolve_period(frame, "0")[0]["start"] == "2024-03-01"
    p, _ = resolve_period(frame, "14")
    assert not p["historical_available"]
    with pytest.raises(ValueError, match="附近没有有效"):
        resolve_period(frame, "4", "2026-10-29")


def test_internal_gap_and_invalid_custom_period():
    frame = nav_frame("2024-01-01", "2024-12-31")
    frame = frame.loc[~frame["date"].between("2024-05-01", "2024-06-01")]
    p, _ = resolve_period(frame, "9")
    assert not p["historical_available"] and "缺口" in p["reason"]
    p, _ = resolve_period(frame, "custom", start_date="2025-01-01")
    assert not p["historical_available"]


def test_fit_does_not_use_origin_or_future_data():
    frame = nav_frame("2020-01-01", "2024-01-01")
    origin = frame.iloc[600]["date"]
    expected = fit_model(frame, origin)
    changed = frame.copy()
    changed.loc[changed["date"] >= origin, "daily_log_return"] = -0.8
    assert fit_model(changed, origin) == expected
    assert pd.Timestamp(expected["training_end"]) < origin


def test_known_path_risk_metrics():
    paths = np.array([[100, 80, 88, 110], [100, 110, 99, 90]], dtype=float)
    metrics = path_metrics(paths, 1)
    np.testing.assert_allclose(metrics["total_return"], [.1, -.1])
    np.testing.assert_allclose(metrics["maximum_drawdown"], [.2, 1 - 90 / 110])
    result = summarize(metrics, {"total_return": 0}, .95)
    assert result["loss_frequency"] == .5
    assert result["var_loss"] == pytest.approx(.09)
    assert result["cvar_loss"] == pytest.approx(.1)
    q = result["metric_distributions"]["total_return"]["percentiles"]
    assert result["var_loss"] == pytest.approx(-q["p05"])
    assert sum(result["metric_distributions"]["total_return"]["histogram"]["counts"]) == 2


def test_one_day_volatility_and_sharpe_are_unavailable():
    metrics = path_metrics(np.array([[1, 1.01], [1, .99]]), 1 / 365.2425)
    assert np.isnan(metrics["annualized_volatility"]).all()
    assert np.isnan(metrics["sharpe_ratio"]).all()
    summary = summarize(metrics, {"total_return": .01})
    assert not summary["metric_distributions"]["sharpe_ratio"]["available"]
    assert summary["metric_distributions"]["downside_volatility"]["available"]


def test_positive_returns_keep_negative_var():
    metrics = path_metrics(np.array([[1, 1.01, 1.02], [1, 1.02, 1.03]]), 1)
    summary = summarize(metrics, {"total_return": .02})
    assert summary["var_loss"] < 0 and summary["cvar_loss"] < 0


def test_tiny_positive_terminal_nav_keeps_correct_annualized_return():
    metrics = path_metrics(np.array([[1.0, 1e-30]]), 10)
    assert metrics["total_return"][0] == -1.0  # 浮点精度下累计收益舍入为-1。
    assert metrics["annualized_return"][0] == pytest.approx(-.999)


def test_gbm_matches_known_terminal_distribution_and_seed():
    fit = {"daily_log_mean": .0001, "daily_log_std": .01}
    first, _, _ = simulate(1, 252, fit, 10000, 19, 1)
    second, _, _ = simulate(1, 252, fit, 10000, 19, 1)
    np.testing.assert_array_equal(first["total_return"], second["total_return"])
    for q in (.05, .5, .95):
        theoretical = np.expm1(.0001 * 252 + .01 * np.sqrt(252) * NormalDist().inv_cdf(q))
        assert np.quantile(first["total_return"], q) == pytest.approx(theoretical, abs=.015)


def test_since_uses_first_twenty_navs_and_starts_at_twentieth_nav():
    frame = nav_frame("2023-01-01", "2024-01-01")
    meta, window = resolve_period(frame, "9")
    config = {"paths": 1000, "train_window": 252, "min_training": 60, "seed": 1,
              "risk_free_rate": 0.0, "confidence": .95}
    result, metrics = evaluate_period(frame, meta, window, config)
    assert result["historical_available"] and result["available"]
    assert result["start"] == str(frame.iloc[19]["date"].date())
    assert result["data_start"] == str(frame.iloc[0]["date"].date())
    assert result["steps"] == len(frame) - 20
    fit = result["fit"]
    assert fit["calibration_mode"] == "initial_20_nav_out_of_sample"
    assert fit["training_nav_count"] == 20 and fit["training_observations"] == 19
    assert fit["training_end"] == result["start"]
    assert fit["daily_log_mean"] == pytest.approx(frame.iloc[1:20]["daily_log_return"].mean())
    assert fit["daily_log_std"] == pytest.approx(frame.iloc[1:20]["daily_log_return"].std(ddof=1))
    assert len(metrics["total_return"]) == 1000


def test_since_fitting_excludes_every_return_after_twentieth_nav():
    frame = nav_frame("2022-01-01", "2024-06-01")
    meta, window = resolve_period(frame, "9", end_date="2023-12-29")
    config = {"paths": 1000, "train_window": 252, "min_training": 60, "seed": 1,
              "risk_free_rate": 0.0, "confidence": .95}
    expected, first_metrics = evaluate_period(frame, meta, window, config)
    changed = frame.copy()
    changed.loc[changed["date"] > pd.Timestamp(meta["start"]), "daily_log_return"] = -.8
    actual, second_metrics = evaluate_period(changed, meta, window, config)
    assert actual["fit"] == expected["fit"]
    assert actual["fit"]["training_end"] == meta["start"] < "2023-12-29"
    np.testing.assert_array_equal(first_metrics["total_return"], second_metrics["total_return"])


def test_explicit_sixty_sample_limit_is_still_respected():
    frame = nav_frame("2024-01-01", "2024-01-31")
    meta, window = resolve_period(frame, "0")
    config = {"paths": 1000, "train_window": 252, "min_training": 60, "seed": 1,
              "risk_free_rate": 0.0, "confidence": .95}
    result, _ = evaluate_period(frame, meta, window, config)
    assert result["historical_available"] and not result["available"]
    assert "起点前" in result["reason"] and "60" in result["reason"]


@pytest.mark.parametrize("code", ["0", "9"])
def test_six_mcp_navs_allow_one_day_but_not_since_warmup(code):
    values = ["1.1756", "1.0437", "1.0431", "1.1040", "1.1396", "0.9862"]
    dates = ["20260928", "20260929", "20260930", "20261001", "20261002", "20261003"]
    frame, _ = load_nav(mcp_payload([{"date": date, "navAccumulated": value}
                                     for date, value in zip(dates, values)]))
    meta, window = resolve_period(frame, code)
    config = {"paths": 1000, "train_window": 252, "min_training": 2, "seed": 1,
              "risk_free_rate": 0.0, "confidence": .95}
    result, metrics = evaluate_period(frame, meta, window, config)
    if code == "9":
        assert not result["available"] and not metrics
        assert "至少21条" in result["reason"] and "仅有6条" in result["reason"]
        return
    assert result["available"] and result["steps"] == 1
    assert result["fit"]["training_observations"] == 3
    assert len(metrics["total_return"]) == 1000
    assert any("样本很少" in note for note in result["notes"])
    assert result["start"] == "2026-10-02"
    assert result["fit"]["training_end"] == "2026-10-01"
    assert not result["simulation"]["metric_distributions"]["sharpe_ratio"]["available"]


@pytest.mark.parametrize("count", [19, 20, 21])
def test_since_warmup_boundary_and_cutoff(count):
    frame = nav_frame("2024-01-01", "2024-04-01")
    end = str(frame.iloc[count - 1]["date"].date())
    meta, window = resolve_period(frame, "9", end_date=end)
    if count <= 20:
        assert not meta["historical_available"] and "至少21条" in meta["reason"]
        return
    config = {"paths": 1000, "train_window": 252, "min_training": 2, "seed": 1,
              "risk_free_rate": 0.0, "confidence": .95}
    result, _ = evaluate_period(frame, meta, window, config)
    assert result["available"] and result["steps"] == 1
    assert result["fit"]["training_observations"] == 19
    assert result["fit"]["training_end"] == str(frame.iloc[19]["date"].date())
    assert result["end"] == end


def test_default_fit_accepts_three_pre_origin_returns():
    frame = nav_frame("2024-01-01", "2024-01-08")
    fit = fit_model(frame, frame.iloc[4]["date"])
    assert fit["training_observations"] == 3


def test_one_return_is_still_insufficient_for_sample_standard_deviation():
    frame = nav_frame("2024-01-01", "2024-01-03")
    with pytest.raises(ValueError, match="少于最低2个"):
        fit_model(frame, frame.iloc[-1]["date"])


def test_mcp_json_reads_accumulated_nav_sorts_and_ignores_unit_nav(tmp_path):
    path = tmp_path / "response.json"
    payload = mcp_payload([
        {"date": "20240103", "navAccumulated": "1.1", "navUnit": "999"},
        {"date": "20240102", "navAccumulated": "1", "navUnit": "not-a-number"}])
    path.write_text(json.dumps(payload), encoding="utf-8-sig")
    frame, source = load_nav(path)
    assert frame.iloc[-1]["daily_return"] == pytest.approx(.1)
    assert frame.iloc[0]["date"] == pd.Timestamp("2024-01-02")
    assert source["value_field"] == "navAccumulated" and source["product_name"] == "测试产品"


def test_mcp_json_conflicting_duplicates_rejected():
    payload = mcp_payload([{"date": "20240102", "navAccumulated": "1"},
                           {"date": "20240102", "navAccumulated": "2"}])
    with pytest.raises(ValueError, match="不同数值"):
        load_nav(payload)


def test_mcp_json_identical_duplicates_are_counted():
    payload = mcp_payload([{"date": "20240102", "navAccumulated": "1"},
                           {"date": "20240102", "navAccumulated": "1.0"},
                           {"date": "20240103", "navAccumulated": "1.1"}])
    frame, source = load_nav(payload)
    assert len(frame) == 2 and source["duplicate_rows_removed"] == 1


@pytest.mark.parametrize("bad", ["0", "-1", "NaN", "Infinity", True, None, [1]])
def test_mcp_json_invalid_nav_never_falls_back_to_unit_nav(bad):
    payload = mcp_payload([{"date": "20240102", "navAccumulated": "1"},
                           {"date": "20240103", "navAccumulated": bad, "navUnit": "1.1"}])
    with pytest.raises(ValueError):
        load_nav(payload)


def test_mcp_failure_pagination_and_invalid_date_are_rejected():
    payload = mcp_payload([{"date": "20240102", "navAccumulated": "1"},
                           {"date": "20240103", "navAccumulated": "1.1"}])
    payload["responseCode"] = "999999"
    with pytest.raises(ValueError, match="返回失败"):
        load_nav(payload)
    payload["responseCode"] = "000000"
    payload["data"]["totalNum"] = 100
    with pytest.raises(ValueError, match="分页"):
        load_nav(payload)
    payload["data"]["totalNum"] = 2
    payload["data"]["list"][0]["date"] = "20240230"
    with pytest.raises(ValueError, match="日期"):
        load_nav(payload)


def test_money_income_compounds_instead_of_taking_income_price_changes():
    payload = mcp_payload([{"date": "20240102", "per10000Income": "100"},
                           {"date": "20240103", "per10000Income": "200"},
                           {"date": "20240104", "per10000Income": "50"}])
    frame, source = load_nav(payload)
    np.testing.assert_allclose(frame["nav"], [1, 1.02, 1.0251])
    np.testing.assert_allclose(frame["daily_return"].dropna(), [.02, .005])
    assert source["nav_basis"] == "per_10000_income_reinvestment_index"


def test_llm_missing_configuration_does_not_request_network(monkeypatch):
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    text, status = call_llm({})
    assert text is None and not status["used"]


def test_llm_adapter_sends_summary_and_records_real_success(monkeypatch):
    for key, value in {"LLM_API_KEY": "test-key", "LLM_BASE_URL": "https://example.com/v1",
                       "LLM_MODEL": "test-model"}.items():
        monkeypatch.setenv(key, value)
    def mock_response(request, timeout):
        assert request.full_url == "https://example.com/v1/chat/completions"
        payload = json.loads(request.data)
        assert "chart_data" not in payload["messages"][1]["content"]
        assert payload["model"] == "test-model"
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "测试分析"},
                                                   "finish_reason": "stop"}]}).encode())
    monkeypatch.setattr("urllib.request.urlopen", mock_response)
    text, status = call_llm({"product_code": "001313", "data_as_of": "2026-09-10",
        "periods": [{"available": False, "chart_data": {"sample_paths": [1, 2]}}]})
    assert text == "测试分析" and status["used"]
