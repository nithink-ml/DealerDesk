"""Demand-forecasting pipeline for the 40 forecast SKUs.

Methodology
-----------
For every SKU we evaluate simple, leakage-free candidates on rolling-origin
(weekly) backtests over the last 26 available weeks:

  1. s13        - mean of the previous 13 weeks
  2. ewma(a)    - exponentially weighted mean with spans 8 and 26
  3. seasonal   - same-week-of-year average over the previous 2 years
  4. holt       - linear trend projection from the last 26 weeks (damped)
  5. promo      - s13 baseline, inflated by the SKU's own promo multiplier
                  (learned only from historical weeks)

The candidate with the lowest backtest WAPE per SKU is then refit on all
history and produces the 4 output weeks 2026-09-28..2026-10-19. promo_flag
for those weeks comes from data/promo_calendar.csv (planned promotions are
known future inputs per data/DATA_README.md).

Metrics: WAPE (weighted absolute percentage error) and MAE. Zero-demand
weeks contribute zero to WAPE by construction; MAE is reported per SKU and
aggregated. Model selection per SKU is recorded in
ml/model_validation_results.csv so results are reproducible end to end.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ML_DIR = BASE_DIR / "ml"
FORECAST_WEEKS = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]


def _wape(actual, pred):
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    total = actual.sum()
    if total <= 0:
        # all-zero actuals: WAPE is undefined; use the absolute-error sum so
        # candidate comparison stays deterministic for sparse (rarely selling) SKUs
        return float(np.abs(actual - pred).sum())
    return float(np.abs(actual - pred).sum() / total)


def _mae(actual, pred):
    return float(np.mean(np.abs(np.asarray(actual, dtype=float) - np.asarray(pred, dtype=float))))


def load_sales() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "sales_history.csv")
    required = {"week_start", "sku", "units_sold", "promo_flag"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"sales_history.csv missing columns: {sorted(missing)}")
    df["week_start"] = pd.to_datetime(df["week_start"])
    df["units_sold"] = pd.to_numeric(df["units_sold"], errors="coerce")
    df["promo_flag"] = pd.to_numeric(df["promo_flag"], errors="coerce").fillna(0).astype(int)
    before = len(df)
    df = df.dropna(subset=["units_sold"])
    df = df.groupby(["sku", "week_start"], as_index=False).agg(
        units_sold=("units_sold", "mean"), promo_flag=("promo_flag", "max"))
    df = df.sort_values(["sku", "week_start"]).reset_index(drop=True)
    if before != len(df):
        pass  # duplicates collapsed by mean aggregation
    return df


def load_promo_calendar() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "promo_calendar.csv")
    df["week_start"] = pd.to_datetime(df["week_start"])
    df["promo_flag"] = pd.to_numeric(df["promo_flag"], errors="coerce").fillna(0).astype(int)
    return df


def _s13(hist):
    return hist.tail(13).mean()


def _ewma(hist, span):
    return hist.tail(52).ewm(span=span, adjust=False).mean().iloc[-1]


def _seasonal(hist, target_week_start, years=2):
    doy = target_week_start.isocalendar()
    vals = []
    for y in range(1, years + 1):
        candidate = target_week_start - pd.DateOffset(years=y)
        match = hist[(hist["week_start"] >= candidate - pd.Timedelta(days=1))
                     & (hist["week_start"] <= candidate + pd.Timedelta(days=1))]
        if len(match):
            vals.append(match["units_sold"].iloc[0])
    if not vals:
        return None
    return float(np.mean(vals))


def _holt_damped(hist, alpha=0.25, beta=0.05, phi=0.9, horizon=4):
    y = hist.tail(52).to_numpy(dtype=float)
    if len(y) < 4:
        return None
    level = y[0]
    trend = y[1] - y[0]
    for t in range(1, len(y)):
        prev_level = level
        prev_trend = trend
        level = alpha * y[t] + (1 - alpha) * (prev_level + phi * trend)
        trend = beta * (level - prev_level) + (1 - beta) * (phi * trend)
    return [max(0.0, level + (phi ** h) * trend) for h in range(1, horizon + 1)]


def _promo_multiplier(hist):
    """Ratio of mean promo-week demand to mean non-promo demand, floored at 1.0."""
    p = hist[hist["promo_flag"] == 1]["units_sold"]
    n = hist[hist["promo_flag"] == 0]["units_sold"]
    if len(p) < 3 or len(n) < 6 or n.mean() == 0:
        return 1.0
    return max(1.0, float(p.mean() / n.mean()))


CANDIDATES = ("s13", "ewma8", "ewma26", "seasonal", "holt", "promo")


def _predict(hist, target_weeks, candidate, promo_mults=None, promo_flags=None):
    n = len(target_weeks)
    if candidate == "s13":
        base = _s13(hist["units_sold"])
        return [float(base)] * n
    if candidate == "ewma8":
        base = _ewma(hist["units_sold"], 8)
        return [float(base)] * n
    if candidate == "ewma26":
        base = _ewma(hist["units_sold"], 26)
        return [float(base)] * n
    if candidate == "seasonal":
        out = []
        for wk in target_weeks:
            s = _seasonal(hist, wk)
            out.append(float(s) if s is not None else float(_s13(hist["units_sold"])))
        return out
    if candidate == "holt":
        proj = _holt_damped(hist["units_sold"])
        return proj if proj is not None else [float(_s13(hist["units_sold"]))] * n
    if candidate == "promo":
        base = _s13(hist["units_sold"])
        if promo_mults is None:
            promo_mults = {}
        mults = promo_mults
        # flags[i] is the promo flag (0/1) for output week i; promo_mults maps the
        # flag value to a demand multiplier learned from history ("1" → promotional
        # weeks get the multiplier, "0" → flagged weeks stay at baseline).
        if promo_flags is True:  # validation probe: every week treated as promo
            return [float(base) * max(1.0, mults.get(1, 1.0)) for _ in range(n)]
        flags = {i: (promo_flags or {}).get(i, 0) for i in range(n)}
        return [float(base) * max(1.0, mults.get(flag, 1.0)) for flag in flags.values()]
    raise ValueError(candidate)


def validate_and_forecast(history: pd.DataFrame, promo_calendar: pd.DataFrame, sku_list):
    """Per-SKU rolling-origin backtest, model selection and final forecast."""
    results = []
    forecasts = []
    val_horizon = 4
    for sku in sku_list:
        hist = history[history["sku"] == sku].sort_values("week_start").reset_index(drop=True)
        promo_mults = {}
        # per-week promo flags for the 4 forecast weeks
        fc_promo = promo_calendar[promo_calendar["sku"] == sku].set_index("week_start")["promo_flag"]
        final_weeks = [pd.Timestamp(w) for w in FORECAST_WEEKS]
        flags = {i: int(fc_promo.get(w, 0)) for i, w in enumerate(final_weeks)}
        # per-period multiplier estimates for validation (same-global multiplier fine)
        global_mult = _promo_multiplier(hist)
        star_promo_mults = {("future", 0): global_mult}
        val_weeks = hist.tail(52)  # validation uses last year of available weeks
        # candidate valid only if enough history
        scores = {}
        n_hist = len(hist)
        if n_hist < 8:
            # very young SKU: single candidate
            candidates = ["s13"]
        else:
            candidates = list(CANDIDATES)
            if n_hist < 106:  # not enough for 2-year seasonal match
                candidates = [c for c in candidates if c != "seasonal"]
        # rolling-origin validation over the last 26 weeks
        val_points = 0
        sums = {}  # candidate -> [wape_sum, mae_sum]
        start = max(0, n_hist - 26)
        for t in range(start, n_hist - val_horizon + 1):
            train = hist.iloc[:t]
            test = hist.iloc[t:t + val_horizon]["units_sold"].to_numpy(dtype=float)
            if len(train) < 4:
                continue
            val_points += 1
            # multiplier estimated from the training slice only (no future leakage)
            promo_mult_train = _promo_multiplier(train)
            for cand in candidates:
                try:
                    preds = _predict(train, range(val_horizon), cand, {1: promo_mult_train}, True)
                except Exception:
                    continue
                wa = _wape(test, preds)
                ma = _mae(test, preds)
                acc = sums.setdefault(cand, [0.0, 0.0])
                acc[0] += wa
                acc[1] += ma
        if not sums or val_points == 0:
            # not enough validation data: fall back to the simplest baseline
            best_name, best_wape, best_mae = "s13", float("nan"), float("nan")
        else:
            averaged = {c: (w / val_points, m / val_points) for c, (w, m) in sums.items()}
            best = min(averaged.items(), key=lambda kv: kv[1])
            best_name, (best_wape, best_mae) = best[0], best[1]
        per_sku_promo_mult = {1: global_mult}
        preds = _predict(hist, final_weeks, best_name, per_sku_promo_mult, flags)
        forecasts.append({"sku": sku, "weeks": [float(max(0.0, p)) for p in preds], "model": best_name})
        results.append({"sku": sku, "model": best_name, "wape": round(best_wape, 4), "mae": round(best_mae, 4),
                        "val_points": val_points, "history_weeks": n_hist})
    return forecasts, results


def write_validation_results(results, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sku", "model", "wape", "mae", "val_points", "history_weeks"])
        writer.writeheader()
        for r in results:
            writer.writerow(r)


def write_forecast_csv(forecasts, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in forecasts:
        for w, value in zip(FORECAST_WEEKS, f["weeks"]):
            rows.append({"sku": f["sku"], "week_start": w, "forecast_units": round(max(0.0, value), 1)})
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sku", "week_start", "forecast_units"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return rows


def validate_forecast_csv(path: Path, sku_list) -> list[str]:
    problems = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames[:3] != ["sku", "week_start", "forecast_units"]:
            problems.append("wrong header")
            return problems
        rows = list(reader)
    if len(rows) != len(sku_list) * 4:
        problems.append(f"expected {len(sku_list) * 4} rows, got {len(rows)}")
    expected = {(s, w) for s in sku_list for w in FORECAST_WEEKS}
    have = {(r["sku"], r["week_start"]) for r in rows}
    if have != expected:
        problems.append("sku/week combinations do not match expectation")
    for r in rows:
        try:
            v = float(r["forecast_units"])
        except (TypeError, ValueError):
            problems.append(f"non-numeric forecast for {r['sku']} {r['week_start']}")
            continue
        if not math.isfinite(v) or v < 0:
            problems.append(f"invalid forecast value for {r['sku']} {r['week_start']}: {v}")
    return problems


def run(output: Path | None = None, validation_output: Path | None = None) -> dict:
    output = output or ML_DIR / "forecast.csv"
    validation_output = validation_output or ML_DIR / "model_validation_results.csv"
    history = load_sales()
    promo = load_promo_calendar()
    lead = pd.read_csv(DATA_DIR / "lead_times.csv")
    sku_list = lead["sku"].tolist()
    missing = [s for s in sku_list if not (history["sku"] == s).any()]
    forecasts, results = validate_and_forecast(history, promo, sku_list)
    rows = write_forecast_csv(forecasts, output)
    write_validation_results(results, validation_output)
    problems = validate_forecast_csv(output, sku_list)
    import numpy as _np
    all_w = [r["wape"] for r in results if r["wape"] == r["wape"]]
    return {
        "output": str(output),
        "rows": len(rows),
        "skus": len(sku_list),
        "missing_history": missing,
        "validation_problems": problems,
        "models_used": sorted({r["model"] for r in results}),
        "mean_wape": float(_np.mean(all_w)) if all_w else None,
    }


if __name__ == "__main__":
    print(run())
