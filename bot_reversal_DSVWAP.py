"""
Bot Reversal+DSVWAP · Anàlisi de Cartera — Entry point.

Aquest fitxer és el punt d'entrada de l'app Streamlit. Tota la lògica
està repartida en mòduls:

  core/             ← lògica pura sense Streamlit
    config.py         StrategyConfig, paths, columnes
    helpers.py        _df_to_csv_bytes, _load_logo_b64, _logo_html
    data_io.py        load_top30_data, load_ohlc, load_msci_world
    indicators.py     ATR, Reversal Entry Zones, Dynamic Swing VWAP
    strategy.py       build_strategy_dataset, run_strategy_backtest
    validation.py     validate_no_lookahead_signal_consistency, run_robustness_comparison

  ui/               ← capa Streamlit
    styles.py         apply_global_styles
    components.py     render_table, _metrics_html, _strategy_summary_html
    charts.py         5 builders d'HTML (chart, replay, equity, timeline, mini-svg)
    tab_info.py       render_informacio_cartera, render_info_empresa
    tab_accio.py      render_accio_individual
    tab_cartera.py    render_backtest_cartera

Per executar: `streamlit run bot_reversal_DSVWAP.py`
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core.config import HISTORICAL_PATH
from core.data_io import load_top30_data, normalize_columns, safe_select_columns
from ui.styles import apply_global_styles
from ui.tab_info import render_informacio_cartera
from ui.tab_accio import render_accio_individual
from ui.tab_cartera import render_backtest_cartera
from ui.tab_fiscal import render_fiscalitat


def main() -> None:
    st.set_page_config(
        page_title="Bot Reversal+DSVWAP · Anàlisi de Cartera",
        page_icon="📊",
        layout="wide",
    )

    apply_global_styles()

    tab_cartera, tab_accio, tab_backtest, tab_fiscal = st.tabs([
        "📊  Informació Cartera",
        "📉  Acció individual",
        "📈  Backtest",
        "🧾  Fiscalitat",
    ])

    with tab_cartera:
        render_informacio_cartera(base_path=".")

    with tab_accio:
        _fund_path = Path(".") / "Top30_FONAMENTALS.csv"
        if _fund_path.exists():
            _df_fund = safe_select_columns(
                load_top30_data(_fund_path), ["Ticker", "Companyia"]
            )
        else:
            _df_fund = pd.DataFrame(columns=["Ticker", "Companyia"])
        render_accio_individual(HISTORICAL_PATH, _df_fund)

    with tab_backtest:
        _base = Path(".")
        _fund_path = _base / "Top30_FONAMENTALS.csv"
        _final_path = _base / "Top30_CLASSIFICACIO_FINAL.csv"
        if _fund_path.exists():
            _df_fund = safe_select_columns(
                load_top30_data(_fund_path), ["Ticker", "Companyia"]
            )
        else:
            _df_fund = pd.DataFrame(columns=["Ticker", "Companyia"])
        _df_final_bt = (
            normalize_columns(load_top30_data(_final_path))
            if _final_path.exists() else None
        )
        render_backtest_cartera(HISTORICAL_PATH, _df_fund, _df_final_bt)

    with tab_fiscal:
        render_fiscalitat()


if __name__ == "__main__":
    main()
