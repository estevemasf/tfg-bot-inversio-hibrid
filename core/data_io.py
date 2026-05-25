"""
Lectura de dades: fonamentals (Top30), OHLCV per ticker, MSCI World.

Aquest mòdul usa `@st.cache_data` per evitar relectures de disc.
Si Streamlit no està disponible, fa servir un decorador no-op
(útil per tests).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.config import MSCI_WORLD_FILENAME

# ─────────────────────────────────────────────────────────────
# Decorador opcional: usa Streamlit si està disponible
# ─────────────────────────────────────────────────────────────
try:
    import streamlit as st
    _cache_data = st.cache_data(show_spinner=False, max_entries=64)
except Exception:
    def _cache_data(fn):
        return fn


# ─────────────────────────────────────────────────────────────
# CARREGA TOP30 (CSV/XLSX de fonamentals)
# ─────────────────────────────────────────────────────────────
@_cache_data
def load_top30_data(file_path: str | Path) -> pd.DataFrame:
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"No s'ha trobat el fitxer: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        df = pd.read_excel(file_path)
    elif suffix == ".csv":
        df = pd.read_csv(file_path, sep=None, engine="python", dtype=str)
    else:
        raise ValueError(f"Format no suportat: {suffix}")
    df.columns = [str(col).strip() for col in df.columns]
    return df


# ─────────────────────────────────────────────────────────────
# UTILITATS DE COLUMNES
# ─────────────────────────────────────────────────────────────
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Neteja noms de columnes: elimina BOM, espais i normalitza encoding."""
    out = df.copy()
    out.columns = [
        str(col).strip().lstrip("\ufeff").lstrip("\u200b")
        for col in out.columns
    ]
    return out


def safe_select_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """
    Selecciona columnes per nom. Si no existeix exactament, intenta trobar-la
    de forma insensible a majúscules i espais. Si no, crea una columna buida.
    """
    out = normalize_columns(df)
    col_map = {c.lower().strip(): c for c in out.columns}
    rename = {}
    for desired in columns:
        if desired not in out.columns:
            key = desired.lower().strip()
            if key in col_map:
                rename[col_map[key]] = desired
            else:
                out[desired] = pd.NA
    if rename:
        out = out.rename(columns=rename)
    return out[columns]


# ─────────────────────────────────────────────────────────────
# CARREGA OHLC D'UN TICKER (matching robust)
# ─────────────────────────────────────────────────────────────
@_cache_data
def load_ohlc(ticker: str, hist_path: Path, company_name: str | None = None) -> pd.DataFrame | None:
    """
    Carrega el CSV OHLCV.
    Format esperat:
        Date, Companyia, Ticker Yahoo original, Ticker Yahoo utilitzat,
        Open, High, Low, Close, Adj Close, Volume

    Matching tolerant a múltiples convencions de nom de fitxer.
    """
    if not hist_path.exists():
        return None

    def _norm(s: str) -> str:
        return (str(s).upper()
                .replace(".", "")
                .replace("-", "")
                .replace("_", "")
                .replace(" ", "")
                .strip())

    ticker_up = ticker.upper().strip()
    ticker_norm = _norm(ticker)

    variants = {ticker_up, ticker_norm}
    if "." in ticker_up:
        base, ext = ticker_up.split(".", 1)
        variants.add(base)
        variants.add(_norm(base))
        if base.isdigit():
            stripped = base.lstrip("0")
            if stripped:
                variants.add(stripped)
                variants.add(f"{stripped}.{ext}")
                variants.add(_norm(f"{stripped}.{ext}"))

    company_norm = _norm(company_name) if company_name else None
    company_tokens = None
    if company_name:
        toks = [_norm(t) for t in str(company_name).split() if len(t) >= 3]
        company_tokens = set(toks) if toks else None

    candidates = []
    for p in hist_path.glob("*.csv"):
        stem_up = p.stem.upper()
        parts = stem_up.split("_")
        parts_norm = [_norm(part) for part in parts]
        stem_norm = _norm(stem_up)

        if ticker_up in parts:
            candidates.append(p); continue
        if any(v in parts_norm for v in variants):
            candidates.append(p); continue
        if stem_norm in variants:
            candidates.append(p); continue

        matched = False
        for v in variants:
            if len(v) >= 3 and any(v in pn for pn in parts_norm):
                candidates.append(p); matched = True; break
        if matched:
            continue

        if company_norm and len(company_norm) >= 5 and company_norm in stem_norm:
            candidates.append(p); continue

        if company_tokens and len(company_tokens) >= 2:
            if all(t in stem_norm for t in company_tokens):
                candidates.append(p); continue

    if not candidates:
        for fn in (f"{ticker}.csv", f"{ticker_up}.csv", f"{ticker.lower()}.csv",
                   f"{ticker.replace('.', '-')}.csv", f"{ticker.replace('-', '.')}.csv"):
            pp = hist_path / fn
            if pp.exists():
                candidates.append(pp)

    if not candidates:
        return None

    p = candidates[0]
    df = pd.read_csv(p, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    if "Date" in df.columns:
        df = df[df["Date"].notna() & (df["Date"].str.strip() != "")].copy()

    rmap = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl == "date":                               rmap[c] = "Date"
        elif cl == "companyia":                        rmap[c] = "Companyia"
        elif cl in ("ticker yahoo utilitzat", "ticker yahoo original"):
            rmap.setdefault(c, "Ticker")
        elif cl == "open":                             rmap[c] = "Open"
        elif cl == "high":                             rmap[c] = "High"
        elif cl == "low":                              rmap[c] = "Low"
        elif cl == "close":                            rmap[c] = "Close"
        elif cl == "adj close":                        rmap[c] = "Adj Close"
        elif cl == "volume":                           rmap[c] = "Volume"

    df = df.rename(columns=rmap)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    for col in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Adj Close" in df.columns and "Close" in df.columns:
        ratio = (df["Adj Close"] / df["Close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        for col in ("Open", "High", "Low", "Close"):
            if col in df.columns:
                df[col] = (df[col] * ratio).round(6)

    return df


# ─────────────────────────────────────────────────────────────
# MSCI WORLD
# ─────────────────────────────────────────────────────────────
@_cache_data
def load_msci_world(indices_path: Path, filename: str = MSCI_WORLD_FILENAME) -> pd.DataFrame | None:
    """
    Carrega l'històric de preus del MSCI World des del CSV.
    Retorna un DataFrame amb columnes ['Date', 'Close'] o None si no existeix.
    """
    indices_path = Path(indices_path)
    csv_path = indices_path / filename
    if not csv_path.exists():
        return None

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    except Exception:
        return None

    df.columns = [str(c).strip() for c in df.columns]
    rmap = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl == "date":                               rmap[c] = "Date"
        elif cl == "close":                            rmap[c] = "Close"
        elif cl in ("adj close", "adj_close", "adjclose"):
            rmap[c] = "Adj Close"
        elif cl == "open":                             rmap[c] = "Open"
        elif cl == "high":                             rmap[c] = "High"
        elif cl == "low":                              rmap[c] = "Low"

    df = df.rename(columns=rmap)
    if "Date" not in df.columns or ("Close" not in df.columns and "Adj Close" not in df.columns):
        return None

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    df["Close"] = pd.to_numeric(df[price_col], errors="coerce")
    df = df.dropna(subset=["Close"])[["Date", "Close"]].reset_index(drop=True)

    return df if not df.empty else None


def _resample_index_to_dates(idx_df: pd.DataFrame, target_dates: list) -> list:
    """
    Alinea les dades del MSCI (o qualsevol índex) amb les dates del backtest.
    Per a cada data objectiu, retorna el Close del MSCI més recent (≤ data).

    Robust a la columna `Date`: si arriba com a string (cas de les corbes
    construïdes a partir d'equity points amb `time` en format ISO), es
    converteix a Timestamp internament. Així el cridador no s'ha de
    preocupar del tipus exacte.
    """
    if idx_df is None or idx_df.empty:
        return [None] * len(target_dates)

    idx_sorted = idx_df.sort_values("Date").reset_index(drop=True).copy()
    # Defensa: assegurem que Date és datetime abans d'usar l'accessor .dt
    if not pd.api.types.is_datetime64_any_dtype(idx_sorted["Date"]):
        idx_sorted["Date"] = pd.to_datetime(idx_sorted["Date"])
    idx_dates = idx_sorted["Date"].dt.strftime("%Y-%m-%d").tolist()
    idx_vals = idx_sorted["Close"].tolist()

    out = []
    ptr = 0
    for d_str in target_dates:
        while ptr + 1 < len(idx_dates) and idx_dates[ptr + 1] <= d_str:
            ptr += 1
        if idx_dates[ptr] <= d_str:
            out.append(idx_vals[ptr])
        else:
            out.append(None)
    return out
