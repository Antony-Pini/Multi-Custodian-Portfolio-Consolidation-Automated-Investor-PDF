"""Consolidation in the fund's base currency (EUR): positions, NAV history,
time-weighted performance, risk statistics and contributions."""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def to_eur(pos: pd.DataFrame, eurusd: float) -> pd.DataFrame:
    pos = pos.copy()
    pos["fx_to_eur"] = np.where(pos["currency"] == "USD", 1 / eurusd, 1.0)
    pos["market_value_eur"] = pos["quantity"] * pos["price"] * pos["fx_to_eur"]
    pos["weight"] = pos["market_value_eur"] / pos["market_value_eur"].sum()
    return pos.sort_values("market_value_eur", ascending=False).reset_index(drop=True)


def nav_history(pos, prices: pd.DataFrame, eurusd: pd.Series, flows: pd.Series) -> pd.DataFrame:
    """Rebuild the daily NAV: priced positions + cash; external flows move the EUR cash line."""
    priced = pos[pos["instrument"].isin(prices.columns)]
    usd = priced["currency"].eq("USD").set_axis(priced["instrument"])
    qty = priced.set_index("instrument")["quantity"]
    local = prices[qty.index] * qty
    fx = pd.DataFrame({c: (1 / eurusd if usd[c] else 1.0) for c in qty.index}, index=prices.index)
    mv = local * fx

    cash = pos[~pos["instrument"].isin(prices.columns)]
    usd_cash = cash.loc[cash["currency"] == "USD", ["quantity", "price"]].prod(axis=1).sum()
    eur_cash_end = cash.loc[cash["currency"] == "EUR", "quantity"].sum()
    later = pd.Series([flows[flows.index > t].sum() for t in prices.index], index=prices.index)
    eur_cash = eur_cash_end - later  # cash before a subscription did not include it yet

    nav = mv.sum(axis=1) + usd_cash / eurusd + eur_cash
    flow_d = flows.reindex(prices.index, fill_value=0.0)
    ret = (nav - flow_d) / nav.shift(1) - 1
    ret.iloc[0] = 0.0
    out = pd.DataFrame({"nav": nav, "flow": flow_d, "return": ret})
    out["index"] = 100 * (1 + out["return"]).cumprod()
    return out, mv


def benchmark(bench: pd.DataFrame, w_eq=0.6) -> pd.Series:
    r = w_eq * bench["equity_index"].pct_change() + (1 - w_eq) * bench["bond_index"].pct_change()
    return 100 * (1 + r.fillna(0)).cumprod()


def stats(idx: pd.Series, rf=0.02) -> dict:
    r = idx.pct_change().dropna()
    years = len(r) / TRADING_DAYS
    total = idx.iloc[-1] / idx.iloc[0] - 1
    ann = (1 + total) ** (1 / years) - 1
    vol = r.std() * np.sqrt(TRADING_DAYS)
    dd = idx / idx.cummax() - 1
    return {"ytd": total, "ann_return": ann, "vol": vol, "sharpe": (ann - rf) / vol,
            "max_dd": dd.min(), "max_dd_date": dd.idxmin()}


def monthly_returns(idx: pd.Series) -> pd.Series:
    m = idx.resample("ME").last()
    return m.pct_change().dropna()  # month-end index already includes the 31/12 base


def contributions(mv: pd.DataFrame, nav: pd.Series, start, end) -> pd.Series:
    """EUR P&L of each line over the period, as a share of starting NAV."""
    d = mv.loc[end] - mv.loc[mv.index[mv.index <= start][-1]]
    return d / nav.loc[nav.index[nav.index <= start][-1]]
