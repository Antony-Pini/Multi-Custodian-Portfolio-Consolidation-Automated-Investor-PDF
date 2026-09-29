# Multi-custodian portfolio consolidation & automated investor reporting

Three custodians, three formats, one investor report — generated in one run.

**All data in this repository is fictional** (simulated prices, fictional fund "Aurelia Capital").

## What it does
1. **Ingests** a US-broker CSV (USD), a French private-bank Excel statement (EUR, `1 234,56`, `dd/mm/yyyy`, banner rows) and a crypto-exchange JSON API dump (epoch ms, exchange ticker aliases).
2. **Checks** every number — 12 automated controls: schema, duplicates, locale parsing, date normalisation, symbol mapping, statement tie-out, price freshness, ±0.5% vendor cross-check, FX coverage, reconciliation against the internal ledger.
3. **Consolidates** in EUR: daily NAV rebuild, time-weighted return net of subscriptions/redemptions, volatility, Sharpe, drawdown, contributions in bp.
4. **Generates** an operations dashboard (PNG), a 4-page investor PDF and an audit log (CSV).

## Run
```bash
pip install pandas openpyxl playwright
python generate_demo_data.py   # fictional raw files -> data/raw
python build.py                # pipeline + dashboard + PDF + portfolio visuals -> output/
```

## Layout
```
pipeline/ingest.py       one adapter per custodian format -> common schema
pipeline/checks.py       data-quality rules and audit log
pipeline/consolidate.py  FX, NAV history, TWR, risk, attribution
render/                  hand-built SVG charts, HTML dashboard, PDF report (headless Chromium)
```
