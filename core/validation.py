"""
Tests de validació: no-look-ahead + comparativa de robustesa.
NO té dependències de Streamlit.
"""
from __future__ import annotations

from dataclasses import fields

import pandas as pd

from core.config import StrategyConfig, EXEC_MODE_LABELS
from core.strategy import build_strategy_dataset, run_strategy_backtest


def validate_no_lookahead_signal_consistency(
    df_ohlc: pd.DataFrame,
    cfg: StrategyConfig,
    start_idx: int = 50,
    sample_every: int = 5,
    max_checks: int = 300,
) -> pd.DataFrame:
    """
    TEST OBLIGATORI DE NO-LOOK-AHEAD.

    Comprova que les senyals `BullishReversal` / `BearishReversal` són
    **causalment estables**: el valor calculat al dia t amb només les
    dades disponibles fins a t ha de coincidir EXACTAMENT amb el valor
    calculat amb el dataset complet.

    Procediment:
      Per a cada t (mostrat cada `sample_every` dies, a partir de
      `start_idx` per deixar warm-up d'indicadors):
        1. Tallem el dataset a [0:t+1]
        2. Recalculem build_strategy_dataset sobre aquesta tall
        3. Comparem les senyals del dia t amb les del recàlcul complet

    Paràmetres:
        df_ohlc:      DataFrame OHLC original
        cfg:          StrategyConfig a provar
        start_idx:    primer índex a validar (per donar marge al warm-up)
        sample_every: cada quants dies es fa la comprovació
        max_checks:   límit de mostres (per controlar temps d'execució)

    Retorna un DataFrame amb columnes:
        Date, bullish_full, bullish_incremental,
        bearish_full, bearish_incremental, match

    Si qualsevol fila té `match=False` → ERROR GREU de look-ahead.
    Un sol missmatch invalida la causalitat del sistema.

    Notes importants:
      • Aquest test valida les senyals EN BRUT (`BullishReversal`/`BearishReversal`),
        no les condicions executives compostes (`LongEntryCond`). Si la senyal
        de reversal és causal, la condició executiva també ho és perquè només
        afegeix una comparació amb el DSVWAP d'aquell mateix dia.
      • Els indicadors usats (ATR, EMA, DSVWAP amb `ds_smooth_anchor=True`)
        són causalment nets: només depenen del passat. Si veiessim mismatches,
        caldria revisar qualsevol índex que miri endavant (p.ex. centered
        rolling windows o interpolacions bidireccionals).
    """
    # Calculem el dataset complet una sola vegada
    full_ds = build_strategy_dataset(df_ohlc, cfg)
    full_ds = full_ds.dropna(subset=["Date"]).reset_index(drop=True)
    n = len(full_ds)
    if n < start_idx + 1:
        return pd.DataFrame(columns=["Date", "bullish_full", "bullish_incremental",
                                     "bearish_full", "bearish_incremental", "match"])

    # Selecció d'índexs a validar
    check_idxs = list(range(start_idx, n, max(1, int(sample_every))))
    if len(check_idxs) > max_checks:
        # Distribuïm uniformement per no perdre cobertura si n és gran
        step = max(1, len(check_idxs) // max_checks)
        check_idxs = check_idxs[::step][:max_checks]

    rows = []
    for t in check_idxs:
        # Tall causal del dataset
        df_partial = df_ohlc.iloc[:t + 1].copy().reset_index(drop=True)
        try:
            partial_ds = build_strategy_dataset(df_partial, cfg)
        except Exception as e:
            # Cap fallada del pipeline en escalfar-se = mismatch de robustesa
            rows.append({
                "Date": str(full_ds.iloc[t]["Date"])[:10],
                "bullish_full": None, "bullish_incremental": None,
                "bearish_full": None, "bearish_incremental": None,
                "match": False, "error": str(e),
            })
            continue

        # Extreu senyals al dia t dels dos càlculs
        full_row = full_ds.iloc[t]
        part_row = partial_ds.iloc[-1]  # l'últim dia del tall és el dia t

        bull_full = bool(full_row.get("BullishReversal", False))
        bull_part = bool(part_row.get("BullishReversal", False))
        bear_full = bool(full_row.get("BearishReversal", False))
        bear_part = bool(part_row.get("BearishReversal", False))

        match = (bull_full == bull_part) and (bear_full == bear_part)

        rows.append({
            "Date": str(full_row["Date"])[:10],
            "bullish_full": bull_full,
            "bullish_incremental": bull_part,
            "bearish_full": bear_full,
            "bearish_incremental": bear_part,
            "match": match,
        })

    return pd.DataFrame(rows)


def run_robustness_comparison(
    df_ohlc: pd.DataFrame,
    base_cfg: StrategyConfig,
    delays: tuple = (0, 1, 2),
    cost_scenarios: dict | None = None,
) -> pd.DataFrame:
    """
    Executa el backtest amb múltiples combinacions de delay i costos
    per auditar la robustesa del sistema. (Position sizing eliminat.)
    """
    if cost_scenarios is None:
        cost_scenarios = {
            "sense_costos": dict(fee_buy_pct=0.0, fee_sell_pct=0.0,
                                 slippage_buy_pct=0.0, slippage_sell_pct=0.0),
            "costos_realistes": dict(fee_buy_pct=0.0025, fee_sell_pct=0.0025,
                                     slippage_buy_pct=0.0005, slippage_sell_pct=0.0005),
        }

    results = []
    for delay in delays:
        for cost_name, cost_kw in cost_scenarios.items():
            overrides = dict(entry_delay_bars=int(delay), **cost_kw)
            kw = {f.name: getattr(base_cfg, f.name) for f in fields(base_cfg)}
            kw.update(overrides)
            cfg_run = StrategyConfig(**kw)

            ds_run = build_strategy_dataset(df_ohlc, cfg_run)
            res = run_strategy_backtest(ds_run, cfg_run)

            results.append({
                "delay": delay,
                "delay_label": EXEC_MODE_LABELS.get(delay, f"delay={delay}"),
                "cost_scenario": cost_name,
                "strat_return_pct": res["strat_total"],
                "bh_return_pct": res["bh_return"],
                "max_dd_pct": res["max_dd"],
                "n_trades": res["n_trades"],
                "win_rate_pct": res["win_rate"],
            })

    return pd.DataFrame(results)
