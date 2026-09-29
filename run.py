"""End-to-end run: raw custodian files in -> checked, consolidated data out.

    python -m pipeline.run
"""
import json
import time
from pathlib import Path

import pandas as pd

from . import checks as qc
from . import consolidate as cs
from .ingest import load_all

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "output"
REPORT_DATE = pd.Timestamp("2026-09-30")


def run() -> dict:
    t0 = time.perf_counter()
    log = qc.CheckLog()

    pos = load_all(RAW, log)

    prices = pd.read_csv(RAW / "vendor_prices_2026.csv", parse_dates=["date"]).pivot(index="date", columns="instrument", values="close")
    fx = pd.read_csv(RAW / "vendor_fx_eurusd.csv", parse_dates=["date"]).set_index("date")["eurusd"]
    bench_raw = pd.read_csv(RAW / "vendor_benchmark_indices.csv", parse_dates=["date"]).set_index("date")
    flows = pd.read_csv(RAW / "capital_flows_2026.csv", parse_dates=["date"]).set_index("date")["amount_eur"]
    ledger = pd.read_csv(RAW / "internal_ledger_positions.csv")

    vendor_close = prices.loc[REPORT_DATE]
    qc.check_totals(pos, log)                              # tie-out on raw statements, before any repricing
    pos = qc.check_staleness(pos, vendor_close, REPORT_DATE, log)
    qc.check_vendor_tolerance(pos, vendor_close, log)
    qc.check_fx(pos, {"EUR": 1.0, "USD": fx.loc[REPORT_DATE]}, log)
    breaks = qc.check_reconciliation(pos, ledger, log)

    pos = cs.to_eur(pos, fx.loc[REPORT_DATE])
    hist, mv = cs.nav_history(pos, prices, fx, flows)
    bench = cs.benchmark(bench_raw)
    hist["benchmark"] = bench

    fund_stats, bench_stats = cs.stats(hist["index"]), cs.stats(bench)
    monthly = pd.DataFrame({"fund": cs.monthly_returns(hist["index"]), "benchmark": cs.monthly_returns(bench)})
    month_start = pd.Timestamp("2026-08-31")
    contrib_m = cs.contributions(mv, hist["nav"], month_start, REPORT_DATE).sort_values()
    contrib_ytd = cs.contributions(mv, hist["nav"], hist.index[0], REPORT_DATE)
    names = pos.set_index("instrument")["name"]
    classes = pos.set_index("instrument")["asset_class"]

    runtime = time.perf_counter() - t0

    OUT.mkdir(exist_ok=True)
    pos.to_csv(OUT / "positions_consolidated.csv", index=False)
    hist.to_csv(OUT / "nav_history.csv")
    log.frame().to_csv(OUT / "data_quality_log.csv", index=False)

    result = {
        "report_date": REPORT_DATE, "positions": pos, "history": hist, "monthly": monthly,
        "fund_stats": fund_stats, "bench_stats": bench_stats, "checks": log.frame(), "check_summary": log.summary(),
        "contrib_month": contrib_m.rename(index=names), "contrib_ytd_by_class": contrib_ytd.groupby(classes).sum(),
        "eurusd": fx.loc[REPORT_DATE], "flows": flows, "breaks": breaks, "runtime_s": runtime,
        "n_sources": 3, "n_positions": len(pos),
    }
    summary = {"nav_eur": round(hist["nav"].iloc[-1], 2), "ytd_twr": round(fund_stats["ytd"], 4),
               "runtime_s": round(runtime, 3), "checks": log.summary()}
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2))
    return result


if __name__ == "__main__":
    r = run()
    print(r["checks"].to_string())
    print(json.dumps({k: v for k, v in json.loads((OUT / 'run_summary.json').read_text()).items()}, indent=2))
    print(r["positions"][["instrument", "asset_class", "market_value_eur", "weight"]].to_string())
    print(r["monthly"].round(4).to_string())
    print(r["fund_stats"], r["bench_stats"])
    print(r["contrib_month"].round(4).to_string())
    print(r["contrib_ytd_by_class"].round(4))
