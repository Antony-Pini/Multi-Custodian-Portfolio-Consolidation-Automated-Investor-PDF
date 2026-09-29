"""Source adapters: each custodian format is mapped to one common schema.

Common schema (one row per position):
    source, instrument, name, asset_class, quantity, price, price_date,
    currency, stated_value
"""
import json
from pathlib import Path

import pandas as pd

from .checks import CheckLog

COLUMNS = ["source", "instrument", "name", "asset_class", "quantity", "price",
           "price_date", "currency", "stated_value"]

TICKER_ALIASES = {"XBT": "BTC"}           # exchange-specific symbols -> internal ids
BANK_IDS = {"FR00DEMO0034": "OAT34", "DE00DEMO0035": "BUND35", "FR0000121014": "MC",
            "FR0000120271": "TTE", "FR0000120073": "AI", "FR00DEMO0MMF": "MMF"}
BANK_CLASSES = {"Actions": "Equity", "Obligations": "Fixed Income",
                "OPCVM Monétaire": "Cash & MMF", "Liquidités": "Cash & MMF"}
CRYPTO_NAMES = {"BTC": "Bitcoin", "ETH": "Ether", "SOL": "Solana", "USDC": "USD Coin"}


def _require(df: pd.DataFrame, cols, source: str, log: CheckLog):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        log.fail("Schema", f"{source}: missing columns {missing}")
        raise ValueError(f"{source}: missing columns {missing}")
    log.ok("Schema", f"{source}: {len(cols)} required fields present")


def parse_fr_number(x):
    """'1 234 567,89' -> 1234567.89 (handles regular and non-breaking spaces)."""
    if pd.isna(x) or str(x).strip() == "":
        return float("nan")
    return float(str(x).replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", "."))


def load_broker(path: Path, log: CheckLog) -> pd.DataFrame:
    df = pd.read_csv(path)
    _require(df, ["Symbol", "Quantity", "MarkPrice", "Currency", "ReportDate"], "Broker CSV", log)
    dupes = df.duplicated().sum()
    if dupes:
        dup_syms = ", ".join(df[df.duplicated()]["Symbol"])
        df = df.drop_duplicates()
        log.fixed("Duplicates", f"{dupes} duplicated {dup_syms} line removed from broker CSV")
    else:
        log.ok("Duplicates", "Broker CSV: no duplicated lines")
    cls = {"STK": "Equity", "ETF-FI": "Fixed Income", "CASH": "Cash & MMF"}
    out = pd.DataFrame({
        "source": "US broker",
        "instrument": df["Symbol"].str.replace(".CASH", "_CASH", regex=False),
        "name": df["Description"],
        "asset_class": df["AssetClass"].map(cls),
        "quantity": df["Quantity"].astype(float),
        "price": df["MarkPrice"].astype(float),
        "price_date": pd.to_datetime(df["ReportDate"], format="%Y-%m-%d"),
        "currency": df["Currency"],
    })
    out["stated_value"] = out["quantity"] * out["price"]
    return out[COLUMNS]


def load_private_bank(path: Path, log: CheckLog) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None, dtype=str)
    # the statement has a free-text banner on top: locate the real header row
    header_row = raw.index[raw.iloc[:, 0].eq("Code ISIN")][0]
    df = raw.iloc[header_row + 1:].copy()
    df.columns = raw.iloc[header_row]
    df = df.dropna(how="all")
    _require(df, ["Code ISIN", "Libellé", "Quantité", "Cours", "Date du cours", "Valorisation"], "Private bank XLSX", log)
    for c in ["Quantité", "Cours", "Valorisation"]:
        df[c] = df[c].map(parse_fr_number)
    log.ok("Locale parsing", f"Private bank XLSX: {len(df)} lines converted from French number format")
    is_cash = df["Code ISIN"].isna()
    out = pd.DataFrame({
        "source": "Private bank",
        "instrument": df["Code ISIN"].map(BANK_IDS).where(~is_cash, "EUR_CASH"),
        "name": df["Libellé"],
        "asset_class": df["Classe d'actifs"].map(BANK_CLASSES),
        "quantity": df["Quantité"].where(~is_cash, df["Valorisation"]),
        "price": df["Cours"].where(~is_cash, 1.0),
        "price_date": pd.to_datetime(df["Date du cours"], format="%d/%m/%Y"),
        "currency": df["Devise"],
        "stated_value": df["Valorisation"],
    })
    return out[COLUMNS].reset_index(drop=True)


def load_exchange(path: Path, log: CheckLog) -> pd.DataFrame:
    api = json.loads(Path(path).read_text())
    _require(pd.DataFrame(api["balances"]), ["asset", "free", "locked"], "Exchange JSON", log)
    ts = pd.to_datetime(api["server_time"], unit="ms", utc=True).tz_convert("Europe/Paris").tz_localize(None).normalize()
    rows, remapped = [], []
    for b in api["balances"]:
        asset = TICKER_ALIASES.get(b["asset"], b["asset"])
        if asset != b["asset"]:
            remapped.append(f"{b['asset']}→{asset}")
        px = float(api["tickers"][f"{b['asset']}USD"])
        qty = float(b["free"]) + float(b["locked"])  # locked (staked / in orders) still belongs to the fund
        rows.append({"source": "Crypto exchange", "instrument": asset, "name": CRYPTO_NAMES[asset],
                     "asset_class": "Cash & MMF" if asset == "USDC" else "Crypto",
                     "quantity": qty, "price": px, "price_date": ts, "currency": "USD",
                     "stated_value": qty * px})
    if remapped:
        log.fixed("Instrument mapping", f"Exchange ticker alias resolved: {', '.join(remapped)}")
    return pd.DataFrame(rows)[COLUMNS]


def load_all(raw_dir: Path, log: CheckLog) -> pd.DataFrame:
    frames = [
        load_broker(raw_dir / "broker_positions_20260930.csv", log),
        load_private_bank(raw_dir / "releve_banque_privee_sept2026.xlsx", log),
        load_exchange(raw_dir / "exchange_balances_20260930.json", log),
    ]
    log.ok("Date normalisation", "3 date formats unified (ISO, dd/mm/yyyy, epoch ms UTC)")
    return pd.concat(frames, ignore_index=True)
