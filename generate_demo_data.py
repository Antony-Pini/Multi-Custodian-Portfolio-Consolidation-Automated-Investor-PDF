"""
Generates FICTIONAL raw data for the demo: three custodian files in three
different formats, a simulated market-data feed, an EUR/USD feed and an
internal trade ledger. Nothing here is real client data.

Errors are injected on purpose so the pipeline's data-quality layer has
something to catch:
  - a duplicated line in the broker CSV
  - a stale price in the private-bank statement
  - an exchange ticker alias (XBT instead of BTC)
  - a 50-share quantity break between the broker and the internal ledger
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).parent / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

import os
SEED = int(os.environ.get("DEMO_SEED", 36))
REPORT_DATE = pd.Timestamp("2026-09-30")
START = pd.Timestamp("2025-12-31")
DAYS = pd.bdate_range(START, REPORT_DATE)

# instrument universe -------------------------------------------------------
# id, name, asset_class, currency, start_price, annual_drift, annual_vol, source
UNIVERSE = [
    ("MSFT",  "Microsoft Corp",            "Equity",       "USD", 480.0,  0.10, 0.26, "broker"),
    ("NVDA",  "NVIDIA Corp",               "Equity",       "USD", 185.0,  0.18, 0.45, "broker"),
    ("AMZN",  "Amazon.com Inc",            "Equity",       "USD", 225.0,  0.09, 0.32, "broker"),
    ("GOOGL", "Alphabet Inc Cl A",         "Equity",       "USD", 310.0,  0.12, 0.30, "broker"),
    ("SPY",   "SPDR S&P 500 ETF",          "Equity",       "USD", 680.0,  0.08, 0.16, "broker"),
    ("TLT",   "iShares 20+Y Treasury ETF", "Fixed Income", "USD",  88.0,  0.02, 0.12, "broker"),
    ("OAT34", "OAT 3.00% 25/11/2034",      "Fixed Income", "EUR",  98.9,  0.01, 0.05, "bank"),
    ("BUND35","Bund 2.50% 15/02/2035",     "Fixed Income", "EUR",  97.6,  0.01, 0.045,"bank"),
    ("MC",    "LVMH",                      "Equity",       "EUR", 640.0,  0.03, 0.28, "bank"),
    ("TTE",   "TotalEnergies",             "Equity",       "EUR",  56.0,  0.06, 0.22, "bank"),
    ("AI",    "Air Liquide",               "Equity",       "EUR", 170.0,  0.07, 0.18, "bank"),
    ("MMF",   "Fonds Monétaire Euro I",    "Cash & MMF",   "EUR", 1027.0, 0.023,0.004,"bank"),
    ("BTC",   "Bitcoin",                   "Crypto",       "USD", 98000., 0.20, 0.55, "exchange"),
    ("ETH",   "Ether",                     "Crypto",       "USD", 3600.0, 0.15, 0.68, "exchange"),
    ("SOL",   "Solana",                    "Crypto",       "USD", 190.0,  0.12, 0.80, "exchange"),
]

QTY = {  # end-of-period holdings
    "MSFT": 3100, "NVDA": 4200, "AMZN": 3800, "GOOGL": 3600, "SPY": 1900, "TLT": 6500,
    "OAT34": 25000, "BUND35": 15000,  # bonds: units of EUR 100 nominal
    "MC": 1100, "TTE": 9000, "AI": 3000, "MMF": 1200,
    "BTC": 18.42, "ETH": 180.5, "SOL": 2500,
}
USDC = 250_000.0
BANK_CASH_END = 850_000.0
FLOWS = {pd.Timestamp("2026-04-01"): 1_000_000.0, pd.Timestamp("2026-07-15"): -400_000.0}

rng = np.random.default_rng(SEED)
n = len(DAYS)
dt = 1 / 252

# a common market factor so equities move together (more realistic)
mkt = rng.standard_normal(n)
prices = {}
for iid, name, ac, ccy, p0, mu, vol, src in UNIVERSE:
    beta = {"Equity": 0.7, "Crypto": 0.4}.get(ac, 0.0)
    z = beta * mkt + np.sqrt(1 - beta**2) * rng.standard_normal(n)
    z[0] = 0.0
    r = (mu - 0.5 * vol**2) * dt + vol * np.sqrt(dt) * z
    prices[iid] = p0 * np.exp(np.cumsum(r))
prices = pd.DataFrame(prices, index=DAYS).round(2)

fx_z = rng.standard_normal(n); fx_z[0] = 0
eurusd = pd.Series(1.172 * np.exp(np.cumsum(0.07 * np.sqrt(dt) * fx_z)), index=DAYS).round(4)

# benchmark components (simulated indices)
b_eq = 100 * np.exp(np.cumsum((0.06 - 0.5 * 0.14**2) * dt + 0.14 * np.sqrt(dt) * (0.8 * mkt + 0.6 * rng.standard_normal(n))))
b_bd = 100 * np.exp(np.cumsum((0.025 - 0.5 * 0.05**2) * dt + 0.05 * np.sqrt(dt) * rng.standard_normal(n)))
b_eq[0] = b_bd[0] = 100

# ---- market data vendor feed (long format, ISO dates) ----------------------
long = prices.stack().rename("close").reset_index()
long.columns = ["date", "instrument", "close"]
long["date"] = long["date"].dt.strftime("%Y-%m-%d")
long.to_csv(RAW / "vendor_prices_2026.csv", index=False)
pd.DataFrame({"date": DAYS.strftime("%Y-%m-%d"), "eurusd": eurusd.values}).to_csv(RAW / "vendor_fx_eurusd.csv", index=False)
pd.DataFrame({"date": DAYS.strftime("%Y-%m-%d"), "equity_index": b_eq.round(4), "bond_index": b_bd.round(4)}).to_csv(RAW / "vendor_benchmark_indices.csv", index=False)

last = prices.iloc[-1]

# ---- 1. US broker: CSV, USD, ISO dates, one duplicated line --------------
rows = []
for iid, name, ac, ccy, *_ , src in UNIVERSE:
    if src != "broker":
        continue
    rows.append({"Symbol": iid, "Description": name, "AssetClass": "STK" if ac == "Equity" else "ETF-FI",
                 "Quantity": QTY[iid], "MarkPrice": last[iid], "CostBasisPrice": round(prices[iid].iloc[0] * 0.93, 2),
                 "Currency": "USD", "ReportDate": REPORT_DATE.strftime("%Y-%m-%d")})
rows.insert(4, dict(rows[3]))  # duplicate GOOGL line (export glitch)
rows.append({"Symbol": "USD.CASH", "Description": "Cash balance", "AssetClass": "CASH", "Quantity": 142_380.55,
             "MarkPrice": 1.0, "CostBasisPrice": 1.0, "Currency": "USD", "ReportDate": REPORT_DATE.strftime("%Y-%m-%d")})
pd.DataFrame(rows).to_csv(RAW / "broker_positions_20260930.csv", index=False)

# ---- 2. French private bank: XLSX, French headers, dd/mm/yyyy, "1 234,56" --
def fr_num(x, d=2):
    s = f"{x:,.{d}f}"
    return s.replace(",", " ").replace(".", ",")

bank_rows = []
isin = {"OAT34": "FR00DEMO0034", "BUND35": "DE00DEMO0035", "MC": "FR0000121014", "TTE": "FR0000120271",
        "AI": "FR0000120073", "MMF": "FR00DEMO0MMF"}
for iid, name, ac, ccy, *_ , src in UNIVERSE:
    if src != "bank":
        continue
    px_date = REPORT_DATE
    px = last[iid]
    if iid == "AI":  # stale price: the bank did not refresh this line
        px_date = pd.Timestamp("2026-09-23")
        px = prices.loc[px_date, iid]
    classe = {"Equity": "Actions", "Fixed Income": "Obligations", "Cash & MMF": "OPCVM Monétaire"}[ac]
    bank_rows.append({"Code ISIN": isin[iid], "Libellé": name, "Classe d'actifs": classe,
                      "Quantité": fr_num(QTY[iid], 0), "Cours": fr_num(px), "Date du cours": px_date.strftime("%d/%m/%Y"),
                      "Devise": "EUR", "Valorisation": fr_num(QTY[iid] * px)})
bank_rows.append({"Code ISIN": "", "Libellé": "Compte courant EUR", "Classe d'actifs": "Liquidités",
                  "Quantité": "", "Cours": "", "Date du cours": REPORT_DATE.strftime("%d/%m/%Y"),
                  "Devise": "EUR", "Valorisation": fr_num(BANK_CASH_END)})
with pd.ExcelWriter(RAW / "releve_banque_privee_sept2026.xlsx") as xw:
    header = pd.DataFrame({"A": ["BANQUE PRIVÉE DÉMO — Relevé de portefeuille", "Client : AURELIA CAPITAL (fictif)",
                                 "Arrêté au 30/09/2026", ""]})
    header.to_excel(xw, index=False, header=False, startrow=0)
    pd.DataFrame(bank_rows).to_excel(xw, index=False, startrow=5)

# ---- 3. crypto exchange: JSON API dump, epoch ms, XBT alias --------------
ts = int(pd.Timestamp("2026-09-30 22:00", tz="UTC").timestamp() * 1000)
api = {"account_id": "demo-7731", "server_time": ts,
       "balances": [
           {"asset": "XBT", "free": str(QTY["BTC"]), "locked": "0.00000000"},
           {"asset": "ETH", "free": "170.5", "locked": "10.0"},
           {"asset": "SOL", "free": str(QTY["SOL"]), "locked": "0"},
           {"asset": "USDC", "free": f"{USDC:.2f}", "locked": "0"}],
       "tickers": {"XBTUSD": f"{last['BTC']:.2f}", "ETHUSD": f"{last['ETH']:.2f}",
                   "SOLUSD": f"{last['SOL']:.2f}", "USDCUSD": "1.0000"}}
(RAW / "exchange_balances_20260930.json").write_text(json.dumps(api, indent=2))

# ---- internal trade ledger (the fund's own books) --------------------------
ledger = []
for iid, q in QTY.items():
    src = next(u[7] for u in UNIVERSE if u[0] == iid)
    q_book = q + 50 if iid == "NVDA" else q  # sale of 50 NVDA on 29/09 never booked internally
    ledger.append({"instrument": iid, "custodian": src, "booked_quantity": q_book})
pd.DataFrame(ledger).to_csv(RAW / "internal_ledger_positions.csv", index=False)

# ---- capital flows ---------------------------------------------------------
pd.DataFrame([{"date": d.strftime("%Y-%m-%d"), "amount_eur": a, "type": "Subscription" if a > 0 else "Redemption"}
              for d, a in FLOWS.items()]).to_csv(RAW / "capital_flows_2026.csv", index=False)

print("raw files:", sorted(p.name for p in RAW.iterdir()))
