"""
Indicadors tècnics: ATR de Wilder, Reversal Entry Zones, Dynamic Swing VWAP.
NO té dependències de Streamlit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import StrategyConfig


# ─────────────────────────────────────────────────────────────
# HELPERS NUMÈRICS
# ─────────────────────────────────────────────────────────────
def _wilder_ma(series: pd.Series, length: int) -> pd.Series:
    """
    Mitjana mòbil de Wilder (smoothed moving average) amb paràmetre N.
    Equivalent a una EMA amb alpha = 1/N.
        Wilder_MA[t] = alpha · X[t] + (1 − alpha) · Wilder_MA[t−1]
    """
    return series.ewm(alpha=1 / max(length, 1), adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    """
    True Range (TR) clàssic de Welles Wilder.
        TR[t] = max( High[t] − Low[t],
                     |High[t] − Close[t−1]|,
                     |Low[t]  − Close[t−1]| )
    """
    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    """
    Average True Range (ATR) calculat amb la suavització de Wilder.
        ATR[t] = WilderMA(TR, N)
    """
    tr = _true_range(df)
    return _wilder_ma(tr, length)


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=max(length, 1), adjust=False).mean()


def _price_source(df: pd.DataFrame, src: str) -> pd.Series:
    src = (src or "hlc3").lower().strip()
    if src == "close":
        return df["Close"]
    if src == "hl2":
        return (df["High"] + df["Low"]) / 2.0
    if src == "ohlc4":
        return (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4.0
    return (df["High"] + df["Low"] + df["Close"]) / 3.0


def _alpha_from_apt(apt: float) -> float:
    apt = max(1.0, float(apt))
    return 1.0 - np.exp(-np.log(2.0) / apt)


# ─────────────────────────────────────────────────────────────
# REVERSAL ENTRY ZONES
# ─────────────────────────────────────────────────────────────
def calc_reversal_entry_zones(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()

    preset_atr = 2.8 if cfg.reversal_preset == "Low" else 3.5
    preset_pct = 0.015 if cfg.reversal_preset == "Low" else 0.02

    atr_now = _atr(out, cfg.reversal_atr_len)

    if cfg.reversal_calc_mode == "High/Low":
        hi_base = out["High"].copy()
        lo_base = out["Low"].copy()
    else:
        hi_base = _ema(out["High"], cfg.reversal_avg_len)
        lo_base = _ema(out["Low"], cfg.reversal_avg_len)

    if cfg.reversal_confirm_bars > 0:
        hi_ref = hi_base.shift(cfg.reversal_confirm_bars)
        lo_ref = lo_base.shift(cfg.reversal_confirm_bars)
        hi_raw_ref = out["High"].shift(cfg.reversal_confirm_bars)
        lo_raw_ref = out["Low"].shift(cfg.reversal_confirm_bars)
    else:
        hi_ref = hi_base
        lo_ref = lo_base
        hi_raw_ref = out["High"]
        lo_raw_ref = out["Low"]

    n = len(out)
    bullish = np.zeros(n, dtype=bool)
    bearish = np.zeros(n, dtype=bool)
    reversal_price = np.full(n, np.nan)
    reversal_dir = np.zeros(n, dtype=int)
    threshold_arr = np.full(n, np.nan)
    bull_strength = np.full(n, np.nan)
    bear_strength = np.full(n, np.nan)

    runHigh = np.nan
    runLow = np.nan
    runHighRaw = np.nan
    runLowRaw = np.nan
    runHighBar = None
    runLowBar = None
    swingDir = 1

    for i in range(n):
        hi_i = hi_ref.iat[i]
        lo_i = lo_ref.iat[i]
        hi_raw_i = hi_raw_ref.iat[i]
        lo_raw_i = lo_raw_ref.iat[i]
        close_i = out["Close"].iat[i]
        atr_i = atr_now.iat[i]

        if pd.isna(hi_i) or pd.isna(lo_i) or pd.isna(close_i):
            continue

        threshold = max(
            float(close_i) * preset_pct / 100.0,
            max(float(cfg.reversal_custom_abs), float(preset_atr) * (0.0 if pd.isna(atr_i) else float(atr_i))),
        )
        threshold_arr[i] = threshold

        if pd.isna(runHigh) or pd.isna(runLow):
            runHigh = float(hi_i)
            runLow = float(lo_i)
            runHighRaw = float(hi_raw_i)
            runLowRaw = float(lo_raw_i)
            runHighBar = i
            runLowBar = i
            swingDir = 1
            continue

        if swingDir == 1:
            if float(hi_i) > runHigh:
                runHigh = float(hi_i)
                runHighRaw = float(hi_raw_i)
                runHighBar = i

            if runHigh - float(lo_i) >= threshold:
                bearish[i] = True
                reversal_price[i] = runHighRaw
                reversal_dir[i] = -1
                bear_strength[i] = (runHigh - float(lo_i)) / threshold if threshold > 0 else 1.0

                swingDir = -1
                runLow = float(lo_i)
                runLowRaw = float(lo_raw_i)
                runLowBar = i
        else:
            if float(lo_i) < runLow:
                runLow = float(lo_i)
                runLowRaw = float(lo_raw_i)
                runLowBar = i

            if float(hi_i) - runLow >= threshold:
                bullish[i] = True
                reversal_price[i] = runLowRaw
                reversal_dir[i] = 1
                bull_strength[i] = (float(hi_i) - runLow) / threshold if threshold > 0 else 1.0

                swingDir = 1
                runHigh = float(hi_i)
                runHighRaw = float(hi_raw_i)
                runHighBar = i

    out["BullishReversal"] = bullish
    out["BearishReversal"] = bearish
    out["BullishStrength"] = bull_strength
    out["BearishStrength"] = bear_strength
    out["ReversalPrice"] = reversal_price
    out["ReversalDir"] = reversal_dir
    out["ReversalThreshold"] = threshold_arr
    return out


# ─────────────────────────────────────────────────────────────
# DYNAMIC SWING VWAP
# ─────────────────────────────────────────────────────────────
def calc_dynamic_swing_vwap(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy().reset_index(drop=True)
    n = len(out)
    if n == 0:
        out["DSVWAP"] = np.nan
        out["DSVWAP_Upper"] = np.nan
        out["DSVWAP_Lower"] = np.nan
        out["DSVWAP_Trend"] = np.nan
        out["DSVWAP_LastSwing"] = np.nan
        out["DSVWAP_Up"] = False
        out["DSVWAP_Down"] = False
        return out

    src = _price_source(out, cfg.ds_src)

    vol_median = out["Volume"].rolling(50, min_periods=1).median().fillna(1.0)
    vol_sma20 = out["Volume"].rolling(20, min_periods=1).mean().fillna(1.0)
    vol_cap = np.maximum(vol_sma20 * 3.0, 1.0)

    vol_proc = out["Volume"].copy().fillna(0.0).astype(float)
    raw_vol = vol_proc.values
    med_vol = vol_median.values
    cap_vol = vol_cap.values

    proc_vol = np.empty(n, dtype=float)
    for i in range(n):
        floor_vol = raw_vol[i] if raw_vol[i] > 0 else med_vol[i]
        capped = min(floor_vol, cap_vol[i]) if cfg.ds_vol_cap else floor_vol
        proc_vol[i] = max(float(capped), 1.0)

    prd = max(2, int(cfg.ds_prd))
    roll_max = out["High"].rolling(prd, min_periods=1).max()
    roll_min = out["Low"].rolling(prd, min_periods=1).min()
    is_swing_high = out["High"] >= roll_max
    is_swing_low = out["Low"] <= roll_min

    atr_len = 50
    atr = _atr(out, atr_len).bfill().fillna(0.0)
    atr_avg = _wilder_ma(atr, atr_len).replace(0, np.nan).fillna(atr)
    ratio = (atr / atr_avg).replace([np.inf, -np.inf], np.nan).fillna(1.0)

    if cfg.ds_use_adapt:
        apt_raw = cfg.ds_base_apt / np.power(ratio, cfg.ds_vol_bias)
    else:
        apt_raw = pd.Series(cfg.ds_base_apt, index=out.index)

    apt_series = apt_raw.clip(lower=5.0, upper=300.0).round()

    vwap_arr = np.full(n, np.nan)
    upper_arr = np.full(n, np.nan)
    lower_arr = np.full(n, np.nan)
    anchored_dir_arr = np.full(n, np.nan)
    last_swing_arr = np.array(["—"] * n, dtype=object)

    ph = np.nan
    pl = np.nan
    phL = 0
    plL = 0
    dir_prev = None
    anchored_dir = 1

    last_low_pivot = np.nan
    last_high_pivot = np.nan

    p_state = float(src.iat[0]) * float(proc_vol[0])
    vol_state = float(proc_vol[0])
    ewma_atr_state = float(atr.iat[0])

    def _step_update(j: int, p_cur: float, v_cur: float, atr_cur: float, smooth_mult: float = 1.0):
        alpha = _alpha_from_apt(float(apt_series.iat[j])) * smooth_mult
        pxv = float(src.iat[j]) * float(proc_vol[j])
        p_new = (1.0 - alpha) * p_cur + alpha * pxv
        v_new = (1.0 - alpha) * v_cur + alpha * float(proc_vol[j])
        atr_new = (1.0 - alpha) * atr_cur + alpha * float(atr.iat[j])
        return p_new, v_new, atr_new

    for i in range(n):
        if bool(is_swing_high.iat[i]):
            ph = float(out["High"].iat[i])
            phL = i
        if bool(is_swing_low.iat[i]):
            pl = float(out["Low"].iat[i])
            plL = i

        dir_curr = 1 if phL > plL else -1
        last_swing_arr[i] = last_swing_arr[i - 1] if i > 0 else "—"

        if dir_prev is None:
            dir_prev = dir_curr
            anchored_dir = dir_curr

        dir_flipped = dir_curr != dir_prev

        if dir_flipped:
            pivot_idx = plL if dir_curr > 0 else phL
            pivot_idx = int(max(0, min(i, pivot_idx)))

            if dir_curr > 0:
                if np.isnan(last_low_pivot):
                    txt = "IL"
                elif pl < last_low_pivot:
                    txt = "LL"
                elif pl > last_low_pivot:
                    txt = "HL"
                else:
                    txt = "EL"
                last_low_pivot = pl
            else:
                if np.isnan(last_high_pivot):
                    txt = "IH"
                elif ph > last_high_pivot:
                    txt = "HH"
                elif ph < last_high_pivot:
                    txt = "LH"
                else:
                    txt = "EH"
                last_high_pivot = ph

            last_swing_arr[i] = txt

            is_first = txt in ("IL", "IH")
            is_llhh = txt in ("LL", "HH")
            do_anchor = is_first or (is_llhh if cfg.ds_only_llhh else True)

            if do_anchor:
                anchored_dir = dir_curr

                p_state = float(src.iat[pivot_idx]) * float(proc_vol[pivot_idx])
                vol_state = float(proc_vol[pivot_idx])
                ewma_atr_state = float(atr.iat[pivot_idx])

                vwap_arr[pivot_idx] = p_state / vol_state if vol_state > 0 else np.nan
                dev0 = ewma_atr_state * cfg.ds_band_mult
                upper_arr[pivot_idx] = vwap_arr[pivot_idx] + dev0
                lower_arr[pivot_idx] = vwap_arr[pivot_idx] - dev0
                anchored_dir_arr[pivot_idx] = anchored_dir

                ramp_bars = 5 if cfg.ds_smooth_anchor else 0

                for j in range(pivot_idx + 1, i + 1):
                    bars_from_seed = j - pivot_idx
                    smooth_mult = 1.0
                    if ramp_bars > 0 and bars_from_seed <= ramp_bars:
                        smooth_mult = 0.5 + 0.5 * (bars_from_seed / ramp_bars)

                    p_state, vol_state, ewma_atr_state = _step_update(
                        j, p_state, vol_state, ewma_atr_state, smooth_mult=smooth_mult
                    )
                    vwap_arr[j] = p_state / vol_state if vol_state > 0 else np.nan
                    dev = ewma_atr_state * cfg.ds_band_mult
                    upper_arr[j] = vwap_arr[j] + dev
                    lower_arr[j] = vwap_arr[j] - dev
                    anchored_dir_arr[j] = anchored_dir
            else:
                p_state, vol_state, ewma_atr_state = _step_update(i, p_state, vol_state, ewma_atr_state)
                vwap_arr[i] = p_state / vol_state if vol_state > 0 else np.nan
                dev = ewma_atr_state * cfg.ds_band_mult
                upper_arr[i] = vwap_arr[i] + dev
                lower_arr[i] = vwap_arr[i] - dev
                anchored_dir_arr[i] = anchored_dir
        else:
            if not cfg.ds_only_llhh:
                anchored_dir = dir_curr

            p_state, vol_state, ewma_atr_state = _step_update(i, p_state, vol_state, ewma_atr_state)
            vwap_arr[i] = p_state / vol_state if vol_state > 0 else np.nan
            dev = ewma_atr_state * cfg.ds_band_mult
            upper_arr[i] = vwap_arr[i] + dev
            lower_arr[i] = vwap_arr[i] - dev
            anchored_dir_arr[i] = anchored_dir

        dir_prev = dir_curr

    out["DSVWAP"] = vwap_arr
    out["DSVWAP_Upper"] = upper_arr
    out["DSVWAP_Lower"] = lower_arr
    out["DSVWAP_Trend"] = anchored_dir_arr
    out["DSVWAP_LastSwing"] = last_swing_arr
    out["DSVWAP_Up"] = out["DSVWAP"] > out["DSVWAP"].shift(1)
    out["DSVWAP_Down"] = out["DSVWAP"] < out["DSVWAP"].shift(1)
    return out
