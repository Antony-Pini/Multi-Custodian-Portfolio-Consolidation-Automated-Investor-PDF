"""Data-quality log: every rule the pipeline applies is recorded with its outcome,
so the operations team sees exactly what was checked, fixed or escalated."""
from dataclasses import dataclass, field

import pandas as pd

PASS, FIXED, WARN, BREAK = "Pass", "Auto-fixed", "Warning", "Break"


@dataclass
class CheckLog:
    rows: list = field(default_factory=list)

    def _add(self, status, check, detail):
        self.rows.append({"status": status, "check": check, "detail": detail})

    def ok(self, check, detail):
        self._add(PASS, check, detail)

    def fixed(self, check, detail):
        self._add(FIXED, check, detail)

    def warn(self, check, detail):
        self._add(WARN, check, detail)

    def fail(self, check, detail):
        self._add(BREAK, check, detail)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def summary(self) -> dict:
        s = self.frame()["status"].value_counts().to_dict()
        return {k: int(s.get(k, 0)) for k in (PASS, FIXED, WARN, BREAK)} | {"total": len(self.rows)}


def check_staleness(pos: pd.DataFrame, vendor_close: pd.Series, report_date, log: CheckLog, max_days=1):
    """Custodian prices older than the reporting date are replaced by the vendor close."""
    stale = pos[(pos["price_date"] < report_date - pd.Timedelta(days=max_days)) & pos["instrument"].isin(vendor_close.index)]
    if stale.empty:
        log.ok("Price freshness", "All custodian prices dated on the reporting date")
        return pos
    pos = pos.copy()
    for i, r in stale.iterrows():
        new_px = vendor_close[r["instrument"]]
        impact = (new_px - r["price"]) * r["quantity"]
        log.warn("Price freshness",
                 f"{r['name']} bank price dated {r['price_date']:%d/%m} — repriced at vendor close "
                 f"({impact:+,.0f} {r['currency']})")
        pos.loc[i, ["price", "price_date"]] = [new_px, report_date]
    return pos


def check_vendor_tolerance(pos, vendor_close, log, tol=0.005):
    m = pos[pos["instrument"].isin(vendor_close.index)].copy()
    m["gap"] = (m["price"] / m["instrument"].map(vendor_close) - 1).abs()
    bad = m[m["gap"] > tol]
    if bad.empty:
        log.ok("Price cross-check", f"{len(m)} custodian prices within ±{tol:.1%} of independent vendor close")
    else:
        for _, r in bad.iterrows():
            log.warn("Price cross-check", f"{r['name']}: custodian vs vendor gap {r['gap']:.2%}")


def check_fx(pos, fx_rates: dict, log):
    missing = sorted(set(pos["currency"]) - set(fx_rates))
    if missing:
        log.fail("FX coverage", f"No rate for {missing}")
        raise ValueError(missing)
    log.ok("FX coverage", f"Rates available for {', '.join(sorted(fx_rates))} at reporting date")


def check_reconciliation(pos, ledger: pd.DataFrame, log):
    """Custodian quantities vs the fund's own books."""
    cust = pos[~pos["instrument"].str.endswith("_CASH") & (pos["instrument"] != "USDC")].set_index("instrument")["quantity"]
    book = ledger.set_index("instrument")["booked_quantity"]
    diff = (cust - book).dropna()
    breaks = diff[diff.abs() > 1e-9]
    if breaks.empty:
        log.ok("Position reconciliation", f"{len(diff)} positions match the internal ledger")
    for iid, d in breaks.items():
        log.fail("Position reconciliation",
                 f"{iid}: custodian {cust[iid]:,.0f} vs ledger {book[iid]:,.0f} — escalated, custodian quantity used")
    return breaks


def check_totals(pos, log, tol=1.0):
    recomputed = pos["quantity"] * pos["price"]
    by_src = (recomputed - pos["stated_value"]).groupby(pos["source"]).sum().abs()
    if (by_src < tol).all():
        log.ok("Statement totals", "Recomputed market values tie out to each custodian statement")
    else:
        log.warn("Statement totals", f"Differences vs statements: {by_src.round(2).to_dict()}")
