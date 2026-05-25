"""
Pipeline d'indicadors + backtest long-only.

Estratègia:
    COMPRA  si  BullishReversal AND  Close > DSVWAP
    VENDA   si  BearishReversal AND  Close < DSVWAP

Modes d'execució (entry_delay_bars):
    0 = Optimista — Close del mateix dia (potencial look-ahead)
    1 = Realista (DEFECTE) — Close del dia següent (sense look-ahead)
    2 = Conservador — Close del dia+2

NO té dependències de Streamlit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import StrategyConfig
from core.indicators import (
    _atr,
    calc_dynamic_swing_vwap,
    calc_reversal_entry_zones,
)


def _compute_position_fractions(df: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    """
    [POSITION SIZING ELIMINAT]
    Sempre retorna una fracció constant del 100% (1.0).

    El sistema actual NO fa position sizing per força del senyal: a cada
    compra s'inverteix el 100% del capital disponible, comprant el màxim
    nombre d'accions enteres possibles. NO hi ha apalancament ni deute.

    La funció es manté com a stub per compatibilitat amb el pipeline
    (`build_strategy_dataset` la crida i guarda el valor a `PosFraction`).
    """
    n = len(df)
    if n == 0:
        return pd.Series(dtype=float)
    return pd.Series(1.0, index=df.index)


# ─────────────────────────────────────────────────────────────
# PIPELINE COMPLETA D'INDICADORS
# ─────────────────────────────────────────────────────────────
# NOTA: NO s'utilitza @st.cache_data aquí perquè el DataFrame d'entrada
# canvia constantment (es filtra per dates seleccionades per l'usuari)
# i Streamlit no pot hashar DataFrames amb tipus mixtos. A més, un cache
# basat només en `cfg` retornaria resultats erronis si canvien les dades.
def build_strategy_dataset(df_ohlc: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """
    Construeix tot el dataset amb indicadors + condicions d'execució.

    OPTIMITZACIÓ: La part costosa (reversal + DSVWAP) NOMÉS depèn dels
    paràmetres dels indicadors. La separem amb cache per evitar recalcular
    quan només canvien les fees o el delay.
    """
    # Construïm una "fingerprint" estable del DataFrame: dates inicial/final +
    # nombre de files + suma del Close. Si dos backtests reben el mateix
    # ticker amb el mateix període, aquesta firma serà idèntica i el cache
    # encertarà. Si canvien les dades (nou període), serà diferent i recalcula.
    if len(df_ohlc) > 0:
        df_fingerprint = (
            str(df_ohlc["Date"].iloc[0]),
            str(df_ohlc["Date"].iloc[-1]),
            len(df_ohlc),
            round(float(df_ohlc["Close"].sum()), 4),
        )
    else:
        df_fingerprint = ("empty", "empty", 0, 0.0)

    # Capa 1 (cara): indicadors purs — cachejada per (df_fingerprint, params_indicadors)
    df = _build_indicators_cached_v2(df_ohlc, df_fingerprint, _indicator_cache_key(cfg))

    # Capa 2 (barata): condicions d'execució amb delay — depèn de cfg.entry_delay_bars
    df = df.copy()  # safe-copy del cached frame
    df["LongEntryCond"] = (
        df["BullishReversal"].fillna(False)
        & (df["Close"] > df["DSVWAP"])
    )
    df["LongExitCond"] = (
        df["BearishReversal"].fillna(False)
        & (df["Close"] < df["DSVWAP"])
    )

    delay = max(0, int(getattr(cfg, "entry_delay_bars", 0)))
    if delay > 0:
        df["ExecEntryCond"] = df["LongEntryCond"].shift(delay).fillna(False).astype(bool)
        df["ExecExitCond"] = df["LongExitCond"].shift(delay).fillna(False).astype(bool)
    else:
        df["ExecEntryCond"] = df["LongEntryCond"]
        df["ExecExitCond"] = df["LongExitCond"]

    return df


# ─────────────────────────────────────────────────────────────
# WARM-UP + RESTRICCIÓ AL PERÍODE D'ESTUDI
# ─────────────────────────────────────────────────────────────
def build_strategy_dataset_with_warmup(
    df_ohlc: pd.DataFrame,
    cfg: StrategyConfig,
    trade_start,        # datetime.date | str | pd.Timestamp
    trade_end,          # datetime.date | str | pd.Timestamp
    warmup_days: int = 365,
) -> pd.DataFrame:
    """
    Calcula els indicadors amb un buffer de warm-up i retalla el dataset
    al període d'operativa. Garanteix que el backtest NO pugui generar
    cap compra/venda fora de [trade_start, trade_end].

    ─────────────────────────────────────────────────────────────
    PER QUÈ EXISTEIX
    ─────────────────────────────────────────────────────────────
    Sense warm-up, els indicadors del sistema (DSVWAP amb ds_prd=55,
    ATR(14), Reversal Entry Zones) tenen valors no convergits durant
    els primers ~55 dies del període seleccionat. A la pràctica, el
    bot no pot operar durant aquest temps (≈2,5 mesos perduts al
    començament del període d'estudi).

    Aquesta funció separa CLARAMENT:
        • "període total carregat" = [trade_start − warmup_days, trade_end]
              → només per estabilitzar els indicadors
        • "període d'operativa"    = [trade_start, trade_end]
              → ÚNIC període on el bot pot comprar i vendre

    ─────────────────────────────────────────────────────────────
    PROCEDIMENT
    ─────────────────────────────────────────────────────────────
        1. Es talla `df_ohlc` a [trade_start − warmup_days, trade_end].
        2. Es calcula `build_strategy_dataset` sobre la sèrie estesa.
           Els indicadors es formen amb el buffer i el shift del delay
           (`ExecEntryCond` / `ExecExitCond`) també es calcula aquí, de
           manera que si hi havia un senyal el darrer dia de warm-up
           amb delay=1, la seva EXECUCIÓ apareix correctament al primer
           dia d'operativa.
        3. Es retalla el resultat a [trade_start, trade_end]. El backtest
           rep aquest dataset retallat i, com que no veu cap fila fora
           del període, és físicament impossible que generi cap operació
           fora d'aquest rang.

    ─────────────────────────────────────────────────────────────
    DEGRADACIÓ ELEGANT
    ─────────────────────────────────────────────────────────────
    Si l'actiu té menys de `warmup_days` dies anteriors a `trade_start`
    disponibles (p.ex. una IPO recent), el warm-up s'escurça
    automàticament. El sistema funciona igualment, però els primers
    dies del període poden tenir indicadors menys estabilitzats.
    Això NO és un error; és la limitació natural de les dades.

    Args:
        df_ohlc: DataFrame OHLC complet de l'actiu (idealment amb dades
                 anteriors a trade_start per al warm-up).
        cfg: Configuració de l'estratègia.
        trade_start: Data inicial del període d'operativa (inclosa).
        trade_end: Data final del període d'operativa (inclosa).
        warmup_days: Dies naturals de buffer (default 365 = un any).

    Returns:
        DataFrame amb les columnes idèntiques a `build_strategy_dataset`,
        retallat a [trade_start, trade_end]. Pot estar buit si `df_ohlc`
        no conté cap fila dins el rang demanat.
    """
    if df_ohlc is None or len(df_ohlc) == 0:
        return df_ohlc.iloc[0:0].copy() if df_ohlc is not None else pd.DataFrame()

    # Normalitzem a Timestamp per a comparacions consistents amb la columna Date.
    trade_start_ts = pd.Timestamp(trade_start)
    trade_end_ts = pd.Timestamp(trade_end)
    warmup_start_ts = trade_start_ts - pd.Timedelta(days=int(max(0, warmup_days)))

    # 1. Tall amb buffer de warm-up
    mask_ext = (df_ohlc["Date"] >= warmup_start_ts) & (df_ohlc["Date"] <= trade_end_ts)
    df_extended = df_ohlc.loc[mask_ext].reset_index(drop=True)

    if df_extended.empty:
        return df_extended

    # 2. Indicadors sobre la sèrie estesa (DSVWAP, ATR, Reversal, ExecEntry/Exit)
    ds_extended = build_strategy_dataset(df_extended, cfg)

    # 3. Retallem al període d'operativa: el backtest NOMÉS veurà aquestes files,
    # per tant no pot generar cap compra/venda fora de [trade_start, trade_end].
    mask_study = (
        (ds_extended["Date"] >= trade_start_ts)
        & (ds_extended["Date"] <= trade_end_ts)
    )
    ds = ds_extended.loc[mask_study].reset_index(drop=True)

    return ds


def _indicator_cache_key(cfg: StrategyConfig) -> tuple:
    """
    Clau cachejable: només els paràmetres que afecten els indicadors.
    Excloem entry_delay_bars, fees, slippage, stops, capital — que NO
    influeixen ni en el reversal ni en el DSVWAP.
    """
    return (
        cfg.reversal_confirm_bars, cfg.reversal_preset, cfg.reversal_calc_mode,
        cfg.reversal_avg_len, cfg.reversal_atr_len, cfg.reversal_custom_abs,
        cfg.ds_prd, cfg.ds_base_apt, cfg.ds_use_adapt, cfg.ds_vol_bias,
        cfg.ds_src, cfg.ds_vol_cap, cfg.ds_smooth_anchor, cfg.ds_only_llhh,
        cfg.ds_band_mult,
    )


# Decorador opcional Streamlit (si està disponible)
try:
    import streamlit as _st
    _cached = _st.cache_data(show_spinner=False, max_entries=64)
except Exception:
    def _cached(fn):
        return fn


@_cached
def _build_indicators_cached_v2(_df_ohlc: pd.DataFrame, df_fingerprint: tuple, ind_key: tuple) -> pd.DataFrame:
    """
    Capa interna: calcula reversal + DSVWAP + ATR + DSVWAP_dist_ATR.

    Streamlit cacheja per (`df_fingerprint`, `ind_key`).

    IMPORTANT: el DataFrame es passa amb prefix `_` perquè Streamlit NO intenti
    fer-li hash (els DataFrames amb Timestamps no són hashejables directament).
    En canvi, el `df_fingerprint` (tupla d'identificació estable: dates inicial/
    final + nombre de files + suma del Close) NO té prefix `_`, així que SÍ
    forma part de la clau cache. Això és crític: dos actius diferents tenen
    fingerprints diferents → cache miss → recàlcul correcte. Sense aquesta
    distinció, tots els actius del mateix període rebrien el mateix resultat
    cachejat (bug greu de cartera).
    """
    # Reconstruïm un cfg "minim" per passar als indicadors
    # (tenen tots els paràmetres que necessiten via ind_key descomprimida)
    (rcb, rp, rcm, ral, ratrl, rca,
     dprd, dapt, dadapt, dvb, dsrc, dvc, dsa, dolllhh, dbm) = ind_key
    cfg_inner = StrategyConfig(
        reversal_confirm_bars=rcb, reversal_preset=rp, reversal_calc_mode=rcm,
        reversal_avg_len=ral, reversal_atr_len=ratrl, reversal_custom_abs=rca,
        ds_prd=dprd, ds_base_apt=dapt, ds_use_adapt=dadapt, ds_vol_bias=dvb,
        ds_src=dsrc, ds_vol_cap=dvc, ds_smooth_anchor=dsa, ds_only_llhh=dolllhh,
        ds_band_mult=dbm,
    )

    df = _df_ohlc.copy().reset_index(drop=True)
    df = calc_reversal_entry_zones(df, cfg_inner)
    df = calc_dynamic_swing_vwap(df, cfg_inner)

    # PosFraction sempre = 1.0 (position sizing eliminat)
    df["PosFraction"] = 1.0

    atr_abs = _atr(df, 14).bfill().fillna(0.0)
    atr_safe = atr_abs.replace(0, np.nan).fillna((df["Close"].abs() * 0.01).replace(0, 1.0))
    df["ATR14"] = atr_abs
    df["ATR_rel"] = (atr_abs / df["Close"].abs().replace(0, np.nan)).fillna(0.0)
    df["DSVWAP_dist_ATR"] = ((df["Close"] - df["DSVWAP"]) / atr_safe).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    return df


# ─────────────────────────────────────────────────────────────
# BACKTEST LONG-ONLY
# ─────────────────────────────────────────────────────────────

def run_strategy_backtest(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Estratègia:
        COMPRA  si  BullishReversal AND  Close > DSVWAP
        VENDA   si  BearishReversal AND  Close < DSVWAP

    ─────────────────────────────────────────────────────────────────
    REGLA PRINCIPAL DEL SISTEMA
    ─────────────────────────────────────────────────────────────────
    La senyal diària queda ASSIGNADA a la data de la barra X, però
    només queda CONFIRMADA al tancament d'aquella barra. En timeframe
    diari, per tant, no és una senyal intradia exacta sinó una senyal
    confirmada de final de sessió (closing-based).

    Això implica que:
      • La detecció de reversal utilitza només dades ja conegudes al
        tancament del dia X (High, Low, Close) i dades anteriors.
      • L'execució de l'ordre no pot fer-se abans del tancament de X,
        perquè aleshores no sabem encara si el criteri es compleix.

    Per tant el mode RECOMANAT és `entry_delay_bars = 1`:
       Detecció (close X) → Ordre emesa post-close → Execució close X+1
    Aquest és l'únic mode que elimina completament el look-ahead bias.

    Modes disponibles:
      delay=0  → [optimista/comparatiu] executa al Close del mateix dia
                 que el senyal. Potencialment no realista perquè en
                 producció no es poden enviar ordres a una barra ja
                 tancada amb execució al mateix close.
      delay=1  → [REALISTA / DEFECTE] executa al Close del dia següent.
                 Cap look-ahead. Forma estàndard de backtest closing-based.
      delay=2  → [conservador] executa al Close del dia+2, dona més
                 confirmació a costa de reactivitat.

    ─────────────────────────────────────────────────────────────────
    Capital invertit:
    ─────────────────────────────────────────────────────────────────
    A cada compra s'inverteix el 100% del capital disponible (sense
    apalancament): es compra el màxim nombre d'accions enteres possibles
    al preu d'execució (ja amb slippage), tenint en compte la comissió
    de compra. La resta (residu d'accions enteres) queda en cash sense
    rendiment fins al tancament de la posició.

    No hi ha deute, ni cost financer, ni position sizing per força del
    senyal — l'estratègia és pura: comprar 100% al senyal i vendre 100%
    al senyal contrari.
    """
    work = df.dropna(subset=["Date", "Close"]).copy().reset_index(drop=True)

    delay = max(0, int(getattr(cfg, "entry_delay_bars", 0)))

    trades = []
    signals = []
    equity_points = []

    capital = float(cfg.capital_inicial)
    position = None

    # Costos i stops (pre-llegits per eficiència)
    fee_buy_pct = float(getattr(cfg, "fee_buy_pct", 0.0) or 0.0)
    fee_sell_pct = float(getattr(cfg, "fee_sell_pct", 0.0) or 0.0)
    slip_buy = float(getattr(cfg, "slippage_buy_pct", 0.0) or 0.0)
    slip_sell = float(getattr(cfg, "slippage_sell_pct", 0.0) or 0.0)
    sl_mult = getattr(cfg, "stop_loss_atr_mult", None)
    tsl_mult = getattr(cfg, "trailing_stop_atr_mult", None)
    for i, row in work.iterrows():
        date_s = str(row["Date"])[:10]
        close = float(row["Close"])

        # ═══════════════════════════════════════════════════════
        # STOPS OPCIONALS: s'avaluen ABANS del check de senyal bearish
        # Si disparen, es força una sortida al Close d'aquesta barra.
        # ═══════════════════════════════════════════════════════
        force_exit_reason = None
        if position is not None:
            # Trailing stop: mantenim el highest-close des de l'entrada
            if tsl_mult is not None and close > position.get("max_close_since_entry", close):
                position["max_close_since_entry"] = close
            atr_entry = position.get("atr_entry", 0.0)
            if atr_entry > 0:
                if sl_mult is not None:
                    sl_price = position["entry_price"] - float(sl_mult) * atr_entry
                    if close <= sl_price:
                        force_exit_reason = "stop_loss"
                if force_exit_reason is None and tsl_mult is not None:
                    trailing_ref = position.get("max_close_since_entry", position["entry_price"])
                    tsl_price = trailing_ref - float(tsl_mult) * atr_entry
                    if close <= tsl_price:
                        force_exit_reason = "trailing_stop"

        # NOTA: el registre d'equity s'ha mogut al FINAL del bucle (després
        # d'ENTRY/EXIT) perquè reflecteixi el wallet NET al tancament del dia
        # i no la valoració MTM pre-acció. Així, els dies de compra l'equity
        # ja inclou els costos embeguts a la posició, i els dies de venda
        # l'equity ja és `capital_out` (post fees i slippage). Veure el bloc
        # marcat amb "EQUITY (post-accions)" al final del for.

        # ENTRY (executa al dia amb confirmació ja passada)
        if position is None and bool(row.get("ExecEntryCond", row.get("LongEntryCond", False))):
            # Dia del senyal original (X − delay). La info de criteris
            # que mostrem al popup ve del dia del senyal, no del dia d'execució.
            sig_idx = max(0, i - delay)
            sig_row = work.iloc[sig_idx]
            sig_date = str(sig_row["Date"])[:10]
            sig_close = float(sig_row["Close"])

            # Preu d'EXECUCIÓ amb slippage (compra desfavorable = paguem més)
            exec_price_buy = close * (1.0 + slip_buy)

            # Sempre invertim el 100% del capital disponible (sense apalancament).
            # El nombre màxim d'accions enteres que podem comprar al preu d'execució
            # tenint en compte la comissió de compra:
            #   capital ≥ shares × exec_price × (1 + fee_buy_pct)
            #   shares ≤ capital / (exec_price × (1 + fee_buy_pct))
            denom = exec_price_buy * (1.0 + fee_buy_pct)
            shares_int = int(np.floor(capital / denom)) if denom > 0 else 0

            # Si no tenim capital ni per 1 acció, el senyal es descarta
            if shares_int <= 0:
                continue

            shares = float(shares_int)
            invested_real = shares * exec_price_buy     # valor brut de les accions (amb slippage)
            # Comissió de compra (descompta capital disponible)
            buy_fee = invested_real * fee_buy_pct
            # SENSE deute, SENSE cash retingut: usem el màxim possible
            # del capital disponible per a accions enteres, i la resta
            # (residu d'accions enteres) queda en cash sense rendiment.
            cash_held = max(0.0, capital - invested_real - buy_fee)

            # ATR del dia del senyal (per stops)
            atr_entry_raw = sig_row.get("ATR14")
            atr_entry = float(atr_entry_raw) if pd.notna(atr_entry_raw) else 0.0

            position = {
                "entry_date": date_s,
                "signal_date": sig_date,
                "entry_price": exec_price_buy,
                "entry_dsvwap": None if pd.isna(row["DSVWAP"]) else round(float(row["DSVWAP"]), 4),
                "shares_int": shares_int,
                "invested": invested_real,
                "cash_held": cash_held,
                "shares": shares,
                "capital_entry": round(capital, 2),
                "entry_idx": i,
                "delay_bars": delay,
                "atr_entry": atr_entry,
                "max_close_since_entry": close,
                "buy_fee_paid": buy_fee,
            }
            # El senyal va guardat amb data d'EXECUCIÓ perquè el gràfic
            # posi el marcador al dia real on s'ha fet l'ordre. Però contenint
            # tota la info del dia del senyal per al popup.
            signals.append({
                "time": date_s,
                "type": "buy",
                "price": close,
                "close": round(close, 4),
                "dsvwap": None if pd.isna(row.get("DSVWAP")) else round(float(row["DSVWAP"]), 4),
                "dsvwap_dist_atr": None if pd.isna(row.get("DSVWAP_dist_ATR")) else round(float(row["DSVWAP_dist_ATR"]), 3),
                "atr": None if pd.isna(row.get("ATR14")) else round(float(row["ATR14"]), 4),
                "atr_rel_pct": None if pd.isna(row.get("ATR_rel")) else round(float(row["ATR_rel"]) * 100, 3),
                "bull_strength": None if pd.isna(sig_row.get("BullishStrength")) else round(float(sig_row["BullishStrength"]), 3),
                "threshold": None if pd.isna(sig_row.get("ReversalThreshold")) else round(float(sig_row["ReversalThreshold"]), 4),
                "shares": int(shares_int),
                "invested": round(invested_real, 2),
                "cash_held": round(cash_held, 2),
                "capital_pre": round(capital, 2),
                "signal_date": sig_date,
                "signal_price": round(sig_close, 4),
                "delay_bars": delay,
            })

        # EXIT (per senyal bearish OR per stop forçat)
        elif position is not None and (force_exit_reason is not None or
                                       bool(row.get("ExecExitCond", row.get("LongExitCond", False)))):
            # Dia del senyal de sortida original (per mostrar al popup).
            # Si surt per stop, el "senyal" és el dia actual mateix.
            if force_exit_reason:
                sig_idx = i
            else:
                sig_idx = max(0, i - delay)
            sig_row = work.iloc[sig_idx]
            sig_date = str(sig_row["Date"])[:10]
            sig_close = float(sig_row["Close"])

            # Preu d'execució amb slippage (venda desfavorable = rebem menys)
            exec_price_sell = close * (1.0 - slip_sell)

            # Venem totes les accions: ingrés brut - comissió de venda
            gross_sell = position["shares"] * exec_price_sell
            sell_fee = gross_sell * fee_sell_pct

            days_held = i - position["entry_idx"]

            # Capital després de tancar la posició (sense deute ni cost financer)
            capital_out = gross_sell - sell_fee + position["cash_held"]

            # Retorn del PREU (mentre estàvem dins), pur
            ret_price = (exec_price_sell / position["entry_price"] - 1.0) * 100.0
            # PNL en € (inclou efecte de costos)
            pnl = capital_out - position["capital_entry"]
            # Retorn sobre el CAPITAL invertit (considera costos i cash residual)
            ret_capital = (capital_out / position["capital_entry"] - 1.0) * 100.0

            # Raó de sortida: per mostrar a la taula
            exit_reason = force_exit_reason or "signal_bearish"

            trades.append({
                "Entrada": position["entry_date"],
                "Preu entrada": round(position["entry_price"], 4),
                "DSVWAP entrada": position["entry_dsvwap"],
                "Accions": int(position["shares_int"]),
                "€ Invertits": round(position["invested"], 2),
                "Sortida": date_s,
                "Preu sortida": round(exec_price_sell, 4),
                "DSVWAP sortida": None if pd.isna(row["DSVWAP"]) else round(float(row["DSVWAP"]), 4),
                "Capital entrada": round(position["capital_entry"], 2),
                "Capital sortida": round(capital_out, 2),
                "Guany/Perdua": round(pnl, 2),
                "Retorn preu (%)": round(ret_price, 2),
                "Retorn (%)": round(ret_capital, 2),
                "Dies": days_held,
                "Motiu sortida": exit_reason,
                "Fees compra": round(position.get("buy_fee_paid", 0.0), 2),
                "Fees venda": round(sell_fee, 2),
                # Fees totals = suma dels DOS components JA arrodonits, perquè
                # la fila reconciliï exactament a la taula (compra + venda).
                "Fees totals": round(
                    round(position.get("buy_fee_paid", 0.0), 2) + round(sell_fee, 2), 2
                ),
            })
            capital = capital_out
            signals.append({
                "time": date_s,
                "type": "sell",
                "price": exec_price_sell,
                "close": round(close, 4),
                "exec_price": round(exec_price_sell, 4),
                "dsvwap": None if pd.isna(row.get("DSVWAP")) else round(float(row["DSVWAP"]), 4),
                "dsvwap_dist_atr": None if pd.isna(row.get("DSVWAP_dist_ATR")) else round(float(row["DSVWAP_dist_ATR"]), 3),
                "atr": None if pd.isna(row.get("ATR14")) else round(float(row["ATR14"]), 4),
                "atr_rel_pct": None if pd.isna(row.get("ATR_rel")) else round(float(row["ATR_rel"]) * 100, 3),
                "bear_strength": None if pd.isna(sig_row.get("BearishStrength")) else round(float(sig_row["BearishStrength"]), 3),
                "threshold": None if pd.isna(sig_row.get("ReversalThreshold")) else round(float(sig_row["ReversalThreshold"]), 4),
                "entry_date": position["entry_date"],
                "entry_price": round(position["entry_price"], 4),
                "shares": int(position["shares_int"]),
                "pnl": round(pnl, 2),
                "ret_pct": round(ret_capital, 2),
                "days": days_held,
                "capital_out": round(capital_out, 2),
                "signal_date": sig_date,
                "signal_price": round(sig_close, 4),
                "delay_bars": delay,
                "exit_reason": exit_reason,
            })
            position = None

        # ═══════════════════════════════════════════════════════
        # EQUITY (post-accions): wallet NET al tancament del dia.
        # • Si no hi ha posició → `capital` (cash, ja descomptades fees
        #   d'eventuals vendes d'aquest dia).
        # • Si hi ha posició → MTM (shares × close + cash residual).
        #   Els costos de compra ja són embeguts: en obrir, `cash_held`
        #   es va calcular com `capital − invested_real − buy_fee`, i
        #   `shares = floor(capital / ((1+slip_buy)·(1+fee_buy_pct)·close))`,
        #   per tant `shares·close + cash_held` ja reflecteix les
        #   pèrdues per fee de compra i slippage de compra.
        # ═══════════════════════════════════════════════════════
        if position is None:
            eq_val = capital
        else:
            eq_val = position["shares"] * close + position["cash_held"]
        equity_points.append({"time": date_s, "value": round(eq_val, 4)})

    # Tancament final si queda posició oberta
    if position is not None and len(work) > 0:
        last = work.iloc[-1]
        close = float(last["Close"])
        date_s = str(last["Date"])[:10]
        days_held = len(work) - 1 - position["entry_idx"]

        exec_price_sell = close * (1.0 - slip_sell)
        gross_sell = position["shares"] * exec_price_sell
        sell_fee = gross_sell * fee_sell_pct

        capital_out = gross_sell - sell_fee + position["cash_held"]
        ret_price = (exec_price_sell / position["entry_price"] - 1.0) * 100.0
        pnl = capital_out - position["capital_entry"]
        ret_capital = (capital_out / position["capital_entry"] - 1.0) * 100.0

        trades.append({
            "Entrada": position["entry_date"],
            "Preu entrada": round(position["entry_price"], 4),
            "DSVWAP entrada": position["entry_dsvwap"],
            "Accions": int(position["shares_int"]),
            "€ Invertits": round(position["invested"], 2),
            "Sortida": date_s + " *",
            "Preu sortida": round(exec_price_sell, 4),
            "DSVWAP sortida": None if pd.isna(last["DSVWAP"]) else round(float(last["DSVWAP"]), 4),
            "Capital entrada": round(position["capital_entry"], 2),
            "Capital sortida": round(capital_out, 2),
            "Guany/Perdua": round(pnl, 2),
            "Retorn preu (%)": round(ret_price, 2),
            "Retorn (%)": round(ret_capital, 2),
            "Dies": days_held,
            "Motiu sortida": "forced_close_eop",
            "Fees compra": round(position.get("buy_fee_paid", 0.0), 2),
            "Fees venda": round(sell_fee, 2),
            "Fees totals": round(
                round(position.get("buy_fee_paid", 0.0), 2) + round(sell_fee, 2), 2
            ),
        })
        capital = capital_out
        signals.append({
            "time": date_s,
            "type": "sell",
            "price": exec_price_sell,
            "close": round(close, 4),
            "exec_price": round(exec_price_sell, 4),
            "dsvwap": None if pd.isna(last.get("DSVWAP")) else round(float(last["DSVWAP"]), 4),
            "dsvwap_dist_atr": None if pd.isna(last.get("DSVWAP_dist_ATR")) else round(float(last["DSVWAP_dist_ATR"]), 3),
            "atr": None if pd.isna(last.get("ATR14")) else round(float(last["ATR14"]), 4),
            "atr_rel_pct": None if pd.isna(last.get("ATR_rel")) else round(float(last["ATR_rel"]) * 100, 3),
            "bear_strength": None,
            "threshold": None if pd.isna(last.get("ReversalThreshold")) else round(float(last["ReversalThreshold"]), 4),
            "entry_date": position["entry_date"],
            "entry_price": round(position["entry_price"], 4),
            "shares": int(position["shares_int"]),
            "pnl": round(pnl, 2),
            "ret_pct": round(ret_capital, 2),
            "days": days_held,
            "capital_out": round(capital_out, 2),
            "forced_close": True,
            "exit_reason": "forced_close_eop",
        })

        # IMPORTANT: el darrer equity_points es va registrar abans del
        # forced_close amb la valoració MTM (shares × close). Aquí
        # l'actualitzem amb el `capital_out` real (post slippage de venda i
        # fee de venda) perquè la corba acabi exactament al wallet NET.
        # Sense aquest override, l'últim punt sobreestima el resultat pel
        # cost de la venda forçada — que és precisament la discrepància
        # entre el KPI ("Estratègia Cartera") i la taula comparativa
        # ("Estratègia") quan hi ha posicions obertes a final del període.
        if equity_points:
            equity_points[-1] = {"time": date_s, "value": round(capital_out, 4)}

    capital_final = round(capital, 2)
    first_close = float(work["Close"].iloc[0])
    last_close = float(work["Close"].iloc[-1])

    # ── Retorn Buy & Hold amb costos (per comparació justa amb l'estratègia) ──
    # S'apliquen:
    #   • Mateixa comissió de compra (fee_buy_pct) i venda (fee_sell_pct) sobre
    #     el capital inicial i el valor final.
    #   • Slippage equivalent (entrada desfavorable + sortida desfavorable).
    #   • Cost anual de manteniment/custòdia prorratejat per dies mantinguts.
    # El resultat és el retorn NET que obtindria un inversor passiu.
    n_days_bh = max(1, (work["Date"].iloc[-1] - work["Date"].iloc[0]).days)
    bh_maintenance_annual = float(getattr(cfg, "bh_annual_maintenance_pct", 0.0) or 0.0)

    # Preu efectiu de compra i venda (slippage sobre el Close)
    bh_buy_price = first_close * (1.0 + slip_buy)
    bh_sell_price = last_close * (1.0 - slip_sell)

    # Accions comprades amb el capital inicial (descomptant comissió de compra)
    # Model: paguem buy_fee i després la resta es converteix en accions.
    bh_buy_fee_rate = fee_buy_pct
    capital_disponible_comprar = cfg.capital_inicial / (1.0 + bh_buy_fee_rate)
    bh_shares = capital_disponible_comprar / bh_buy_price if bh_buy_price > 0 else 0.0
    bh_buy_fee = capital_disponible_comprar * bh_buy_fee_rate

    # Valor final brut a la venda
    bh_gross_sell = bh_shares * bh_sell_price
    bh_sell_fee = bh_gross_sell * fee_sell_pct

    # Cost de manteniment anual prorratejat (aproximació: sobre la mitjana del
    # valor mantingut; per simplicitat, sobre el capital inicial, que és el que
    # faria un broker típic sobre el valor de la cartera al final de cada any)
    bh_maintenance_cost = cfg.capital_inicial * bh_maintenance_annual * n_days_bh / 365.0

    bh_capital_final = bh_gross_sell - bh_sell_fee - bh_maintenance_cost
    bh_return = round((bh_capital_final / cfg.capital_inicial - 1.0) * 100.0, 2)
    bh_capital_final = round(bh_capital_final, 2)

    # ── Corba d'EQUITY del Buy & Hold per dia (NET) ────────────────────────
    # Genera una sèrie equivalent a `equity_points` però per l'estratègia
    # passiva Buy & Hold. Garanties:
    #   • bh_equity[0]  = capital_inicial            (cash, abans de comprar)
    #   • bh_equity[N]  = bh_capital_final            (post venda forçada)
    #   • bh_equity[i]  = shares · close_i − manteniment_acumulat_i
    #                                                (intra-període, MTM net)
    # Així, calcular ret = bh_equity[-1] / bh_equity[0] − 1 dona EXACTAMENT
    # el mateix valor que `bh_return` (el que apareix al KPI top de la
    # cartera). Això elimina la discrepància gross/NET que tenia la taula
    # comparativa, on s'usava un índex sintètic de preus sense costos.
    bh_equity: list[dict] = []
    if len(work) > 0:
        start_date = work["Date"].iloc[0]
        n_work = len(work)
        for j in range(n_work):
            row_j = work.iloc[j]
            date_j = str(row_j["Date"])[:10]
            close_j = float(row_j["Close"])
            days_j = max(0, (row_j["Date"] - start_date).days)
            # Manteniment acumulat fins al dia j (prorratejat per dies naturals)
            maint_j = cfg.capital_inicial * bh_maintenance_annual * days_j / 365.0

            if j == 0:
                # Dia 0: el wallet té el capital inicial en cash, igual que
                # l'equity de l'estratègia (encara no s'ha entrat al mercat).
                # La compra de B&H "instantània" al close del dia 0 farà que
                # bh_equity[1] ja sigui MTM post-compra (shares × close_1).
                value_j = float(cfg.capital_inicial)
            elif j < n_work - 1:
                # Intra-període: valoració MTM de les shares B&H menys
                # manteniment acumulat. bh_shares ja porta embeguts els
                # costos de compra (fee + slippage).
                value_j = bh_shares * close_j - maint_j
            else:
                # Últim dia: aplicada la venda forçada → coincideix exacta-
                # ment amb el bh_capital_final del KPI.
                value_j = float(bh_capital_final)

            bh_equity.append({"time": date_j, "value": round(value_j, 4)})

    # Retorn brut del B&H (sense costos) per a debugging/comparació
    bh_return_gross = round((last_close / first_close - 1.0) * 100.0, 2)

    strat_total = round((capital_final / cfg.capital_inicial - 1.0) * 100.0, 2)

    n_trades = len(trades)
    n_win = sum(1 for t in trades if t["Retorn (%)"] > 0)
    win_rate = round(n_win / n_trades * 100.0, 1) if n_trades else 0.0

    # Drawdown estratègia
    eq_series = pd.Series([p["value"] for p in equity_points], index=pd.to_datetime([p["time"] for p in equity_points]))
    running_max = eq_series.cummax()
    dd = (eq_series / running_max - 1.0) * 100.0
    max_dd = round(float(dd.min()), 2) if len(dd) else 0.0

    # Higiene: assegurem que els senyals NO comencin amb una venda orfe
    # (si per la raó que fos el primer senyal fos 'sell', el traiem).
    # Això NO pot passar amb la lògica actual (`position is None` filtra),
    # però deixem aquest guardià per robustesa al gràfic i al reproductor.
    while signals and signals[0].get("type") == "sell":
        signals.pop(0)

    # ── Agregats de comissions de l'ESTRATÈGIA ─────────────────────────────
    # Suma de totes les comissions pagades al llarg del backtest. Com que es
    # deriven de cada operació i les operacions es recalculen sencerament
    # quan canvia `cfg.fee_buy_pct` / `cfg.fee_sell_pct`, aquests totals
    # també es recalculen automàticament en modificar el % de comissió.
    total_fees_buy = round(sum(float(t.get("Fees compra", 0.0)) for t in trades), 2)
    total_fees_sell = round(sum(float(t.get("Fees venda", 0.0)) for t in trades), 2)
    # total_fees = suma de les dues columnes JA arrodonides → la fila de
    # totals de la taula reconcilia exactament amb les columnes individuals.
    total_fees = round(total_fees_buy + total_fees_sell, 2)
    # Pes de les comissions sobre el capital inicial (referència d'impacte)
    total_fees_pct = round(
        total_fees / cfg.capital_inicial * 100.0, 3
    ) if cfg.capital_inicial > 0 else 0.0

    # ── Agregats de comissions del BUY & HOLD ──────────────────────────────
    # El B&H fa exactament 1 compra + 1 venda. `bh_buy_fee` i `bh_sell_fee`
    # ja s'han calculat més amunt amb els mateixos percentatges.
    bh_total_fees = round(bh_buy_fee + bh_sell_fee, 2)

    return {
        "dataset": work,
        "trades": trades,
        "signals": signals,
        "equity": equity_points,
        "bh_equity": bh_equity,         # NOU: corba B&H per dia (NET, costos inclosos)
        "capital_inicial": round(cfg.capital_inicial, 2),
        "capital_final": capital_final,
        "strat_total": strat_total,
        "bh_return": bh_return,
        "bh_return_gross": bh_return_gross,  # sense costos (per debug/comparació)
        "bh_capital_final": bh_capital_final,
        "n_trades": n_trades,
        "n_win": n_win,
        "win_rate": win_rate,
        "max_dd": max_dd,
        # ── NOU: agregats de comissions (recalculats amb el % de fee) ──
        "total_fees_buy": total_fees_buy,      # € comissions de compra (estratègia)
        "total_fees_sell": total_fees_sell,    # € comissions de venda (estratègia)
        "total_fees": total_fees,              # € comissions totals (estratègia)
        "total_fees_pct": total_fees_pct,      # % sobre capital inicial
        "bh_buy_fee": round(bh_buy_fee, 2),    # € comissió compra (B&H)
        "bh_sell_fee": round(bh_sell_fee, 2),  # € comissió venda (B&H)
        "bh_total_fees": bh_total_fees,        # € comissions totals (B&H)
    }


# ─────────────────────────────────────────────────────────────
# WRAPPER CACHEJABLE PER ACTIU (ús a Backtest Cartera)
# Engloba load + indicators + backtest amb una sola crida cachejada.
# ─────────────────────────────────────────────────────────────
def _exec_cache_key(cfg: StrategyConfig) -> tuple:
    """Paràmetres que afecten al backtest (no als indicadors)."""
    return (
        cfg.entry_delay_bars,
        cfg.fee_buy_pct, cfg.fee_sell_pct,
        cfg.slippage_buy_pct, cfg.slippage_sell_pct,
        cfg.bh_annual_maintenance_pct,
        cfg.stop_loss_atr_mult, cfg.trailing_stop_atr_mult,
        cfg.capital_inicial,
    )


@_cached
def compute_asset_backtest_cached(
    ticker: str,
    hist_path_str: str,
    company: str,
    date_from_iso: str,
    date_to_iso: str,
    ind_key: tuple,
    exec_key: tuple,
    warmup_days: int = 365,
) -> dict | None:
    """
    Wrapper cachejat per la pestanya 'Backtest Cartera'.

    Engloba en una sola crida:
        1. load_ohlc(ticker)
        2. build_strategy_dataset_with_warmup (indicadors amb buffer
           + retall a [date_from_iso, date_to_iso])
        3. run_strategy_backtest sobre el dataset retallat

    El warm-up garanteix que el primer dia de [date_from_iso, date_to_iso]
    ja tingui DSVWAP/ATR/Reversal estabilitzats; el retall posterior
    garanteix que cap operació no es pugui executar fora del període.

    Retorna un dict amb 'dataset' i 'result' o None si no hi ha dades.
    Streamlit cacheja la combinació (ticker, hist_path, dates, ind_key,
    exec_key, warmup_days).
    """
    from pathlib import Path
    from core.data_io import load_ohlc

    df_ohlc = load_ohlc(ticker, Path(hist_path_str), company_name=company)
    if df_ohlc is None or df_ohlc.empty:
        return None

    # Reconstrucció de cfg a partir de les dues claus
    (rcb, rp, rcm, ral, ratrl, rca,
     dprd, dapt, dadapt, dvb, dsrc, dvc, dsa, dolllhh, dbm) = ind_key
    (delay, fee_b, fee_s, slip_b, slip_s, bh_maint, sl_mult, tsl_mult, cap) = exec_key

    cfg = StrategyConfig(
        reversal_confirm_bars=rcb, reversal_preset=rp, reversal_calc_mode=rcm,
        reversal_avg_len=ral, reversal_atr_len=ratrl, reversal_custom_abs=rca,
        ds_prd=dprd, ds_base_apt=dapt, ds_use_adapt=dadapt, ds_vol_bias=dvb,
        ds_src=dsrc, ds_vol_cap=dvc, ds_smooth_anchor=dsa, ds_only_llhh=dolllhh,
        ds_band_mult=dbm,
        entry_delay_bars=delay,
        fee_buy_pct=fee_b, fee_sell_pct=fee_s,
        slippage_buy_pct=slip_b, slippage_sell_pct=slip_s,
        bh_annual_maintenance_pct=bh_maint,
        stop_loss_atr_mult=sl_mult, trailing_stop_atr_mult=tsl_mult,
        capital_inicial=cap,
    )

    # Warm-up + retall al període d'operativa en una sola crida.
    ds = build_strategy_dataset_with_warmup(
        df_ohlc, cfg,
        trade_start=date_from_iso, trade_end=date_to_iso,
        warmup_days=warmup_days,
    )
    if ds.empty:
        return None

    res = run_strategy_backtest(ds, cfg)
    return {"dataset": ds, "result": res}


# ─────────────────────────────────────────────────────────────
# CORBA D'EQUITY DEL MSCI WORLD TRACTAT COM A ETF
# ─────────────────────────────────────────────────────────────
def build_msci_etf_equity(
    msci_df: pd.DataFrame,
    capital_inicial: float,
    fee_pct: float = 0.0,
    slippage_buy_pct: float = 0.0,
    slippage_sell_pct: float = 0.0,
    ter_annual_pct: float = 0.002,
) -> dict:
    """
    Modela la inversió en un ETF que rèplica el MSCI World amb costos
    realistes: comissió de compra/venda, slippage, i TER anual.

    Permet comparar l'estratègia activa amb un "benchmark realista" en
    lloc de l'índex pur. La lògica és idèntica a la del Buy & Hold:
        • 1 compra al primer dia del període
        • Mantenir durant tot el període pagant TER prorratejat
        • 1 venda al darrer dia

    Args:
        msci_df: DataFrame amb columnes Date i Close (preus de l'índex).
                 S'espera ja retallat al període que es vol analitzar.
        capital_inicial: € a invertir.
        fee_pct: comissió per operació (en tant per u, p.ex. 0.0025 = 0.25%).
        slippage_buy_pct: slippage a la compra (0.0005 = 0.05%).
        slippage_sell_pct: slippage a la venda.
        ter_annual_pct: TER anual de l'ETF (0.002 = 0.20% anual).

    Returns:
        Dict amb les mateixes claus que el resultat d'un B&H:
            • equity         : llista de {time, value} per dia
            • capital_inicial: € invertits
            • capital_final  : € finals després de la venda
            • return_pct     : retorn total (%)
            • return_gross   : retorn brut (sense costos, només preu)
            • buy_fee, sell_fee, total_fees: costos €
            • ter_cost       : cost total de TER €
    """
    empty = {
        "equity": [], "capital_inicial": round(capital_inicial, 2),
        "capital_final": round(capital_inicial, 2), "return_pct": 0.0,
        "return_gross": 0.0, "buy_fee": 0.0, "sell_fee": 0.0,
        "total_fees": 0.0, "ter_cost": 0.0,
    }
    if msci_df is None or msci_df.empty or capital_inicial <= 0:
        return empty

    msci = msci_df.sort_values("Date").reset_index(drop=True)
    first_close = float(msci["Close"].iloc[0])
    last_close = float(msci["Close"].iloc[-1])
    if first_close <= 0:
        return empty

    n_days = max(1, (msci["Date"].iloc[-1] - msci["Date"].iloc[0]).days)

    # ── Compra inicial (mateixa lògica que el B&H) ────────────────────────
    # El capital es divideix entre les "accions" de l'ETF al preu d'execució
    # (close + slippage de compra). Es paga la comissió de compra.
    buy_price = first_close * (1.0 + slippage_buy_pct)
    capital_disponible = capital_inicial / (1.0 + fee_pct)
    n_shares = capital_disponible / buy_price if buy_price > 0 else 0.0
    buy_fee = capital_disponible * fee_pct

    # ── Venda final ───────────────────────────────────────────────────────
    sell_price = last_close * (1.0 - slippage_sell_pct)
    gross_sell = n_shares * sell_price
    sell_fee = gross_sell * fee_pct

    # ── TER anual prorratejat sobre el capital inicial ────────────────────
    # Aproximació consistent amb el manteniment del B&H: aplicat sobre el
    # principal inicial × dies / 365. (En realitat el TER s'aplicaria sobre
    # el valor mantingut, però la diferència és menor i fa la comparació
    # més directa amb el B&H.)
    ter_cost = capital_inicial * ter_annual_pct * n_days / 365.0

    capital_final = gross_sell - sell_fee - ter_cost
    return_pct = (capital_final / capital_inicial - 1.0) * 100.0
    return_gross = (last_close / first_close - 1.0) * 100.0

    # ── Corba d'equity per dia (MTM amb TER acumulat) ─────────────────────
    # Mateixa estructura que el bh_equity de run_strategy_backtest:
    #   • equity[0] = capital_inicial (encara no s'ha comprat)
    #   • equity[i] intra-període = shares × close_i − TER_acumulat_i
    #   • equity[N] = capital_final (post venda)
    equity_points = []
    start_date = msci["Date"].iloc[0]
    n_pts = len(msci)
    for j in range(n_pts):
        row_j = msci.iloc[j]
        close_j = float(row_j["Close"])
        days_j = max(0, (row_j["Date"] - start_date).days)
        ter_j = capital_inicial * ter_annual_pct * days_j / 365.0

        if j == 0:
            value_j = float(capital_inicial)
        elif j < n_pts - 1:
            value_j = n_shares * close_j - ter_j
        else:
            value_j = float(capital_final)
        equity_points.append({
            "time": str(row_j["Date"])[:10],
            "value": round(value_j, 4),
        })

    return {
        "equity": equity_points,
        "capital_inicial": round(capital_inicial, 2),
        "capital_final": round(capital_final, 2),
        "return_pct": round(return_pct, 2),
        "return_gross": round(return_gross, 2),
        "buy_fee": round(buy_fee, 2),
        "sell_fee": round(sell_fee, 2),
        "total_fees": round(buy_fee + sell_fee, 2),
        "ter_cost": round(ter_cost, 2),
    }

