"""
Pestanya 'Backtest Cartera':
  • Càrrega dels 30 actius amb pesos (Pes Cartera o Sharpe-derived)
  • KPIs agregats
  • 4 sub-pestanyes: Resultat per actiu (cards expandibles) ·
                    Reproducció individual · Línia temporal · Corba de capital
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core.config import (
    StrategyConfig,
    INDICES_PATH,
    MSCI_WORLD_FILENAME,
    STUDY_START_DATE,
    STUDY_END_DATE,
    WARMUP_BUFFER_DAYS,
)
from core.data_io import load_ohlc, load_msci_world
from core.helpers import _df_to_csv_bytes, _logo_html, _load_logo_b64
from core.strategy import (
    build_strategy_dataset,
    build_strategy_dataset_with_warmup,
    run_strategy_backtest,
    build_msci_etf_equity,
)
from ui.charts import (
    _build_replay_chart_html,
    _build_portfolio_timeline_html,
    _build_equity_curve_html,
    _build_mini_equity_svg,
)
from ui.components import render_table, subtab_intro, render_page_header
from ui.styles import apply_global_styles
from core.fiscal import (
    compute_tax_summary, apply_tax_to_equity, sales_from_trades,
    TaxableSale, _to_date,
)
from ui.fiscal_ui import tax_config_from_state, render_yearly_tax_table


def _find_weight_column(df: pd.DataFrame) -> str | None:
    """
    Intenta trobar la columna de PES en cartera a df_final.
    Prioritza explícitament noms de pes/weight; evita confondre amb scores.

    El pes detectat ha de coincidir amb el valor mostrat a 'Informació empresa'.
    """
    if df is None or df.empty:
        return None

    priority_patterns = [
        "pes en cartera (%)", "pes en cartera", "pes cartera (%)", "pes cartera",
        "pes (%)", "pes %", "pes",
        "weight (%)", "weight %", "weight",
        "percentatge cartera", "percentatge",
        "% cartera", "%",
    ]

    col_lower = {c.lower().strip(): c for c in df.columns}
    skip = {"ticker", "companyia"}

    # 1) Coincidència exacta
    for pattern in priority_patterns:
        if pattern in col_lower and pattern not in skip:
            return col_lower[pattern]

    # 2) Substring + validació numèrica
    for pattern in priority_patterns:
        for c_low, c_orig in col_lower.items():
            if c_low in skip:
                continue
            if pattern in c_low:
                try:
                    s = pd.to_numeric(
                        df[c_orig].astype(str)
                            .str.replace(",", ".", regex=False)
                            .str.replace("%", "", regex=False),
                        errors="coerce",
                    )
                    if s.notna().sum() > 0:
                        return c_orig
                except Exception:
                    continue

    return None


def _compute_portfolio_weights(
    valid_tickers: list[str],
    df_final: pd.DataFrame | None,
    returns_dict: dict[str, pd.Series],
    use_fundamental: bool,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], str | None]:
    """
    Calcula els pesos per assignar capital a cada actiu.

    Retorna:
      - weights: {ticker: w} en format fraccional (0.0295 = 2.95%)
      - fund_raw: pes fonamental brut (en percentatge per mostrar)
      - sharpe_raw: ràtio de Sharpe anual (només informatiu, NO afecta el pes)
      - weight_col_used: nom de la columna de pes emprada (o None)

    Lògica:
      - Si use_fundamental=True → weights = pes directe de la classificació fonamental
        (coincideix exactament amb 'Informació empresa').
      - Si use_fundamental=False → equal-weight (1/N).
      - Actius sense dades suficients no reben pes: el capital queda en efectiu.
        NO es renormalitza, per preservar els pesos originals.
    """
    n = len(valid_tickers)
    if n == 0:
        return {}, {}, {}, None

    equal_w = {t: 1.0 / n for t in valid_tickers}

    # ── Sharpe anual (només informatiu) ──────────────
    sharpe_raw = {}
    for t in valid_tickers:
        rets = returns_dict.get(t)
        if rets is None or len(rets) < 20:
            sharpe_raw[t] = 0.0
            continue
        std = float(rets.std())
        if std <= 0 or pd.isna(std):
            sharpe_raw[t] = 0.0
            continue
        sr_ann = (float(rets.mean()) * 252.0) / (std * (252.0 ** 0.5))
        sharpe_raw[t] = sr_ann

    # ── Equal-weight si l'usuari ho ha demanat ───────
    if not use_fundamental:
        fund_raw_eq = {t: 100.0 / n for t in valid_tickers}
        return equal_w, fund_raw_eq, sharpe_raw, None

    # ── Pes directe de la classificació fonamental ───
    if df_final is None or df_final.empty:
        # No hi ha classificació → fallback equal-weight
        fund_raw_eq = {t: 100.0 / n for t in valid_tickers}
        return equal_w, fund_raw_eq, sharpe_raw, None

    weight_col_used = _find_weight_column(df_final)
    ticker_col = None
    for c in df_final.columns:
        if c.strip().lower() == "ticker":
            ticker_col = c
            break

    if weight_col_used is None or ticker_col is None:
        # No s'ha trobat columna de pes → fallback equal-weight
        fund_raw_eq = {t: 100.0 / n for t in valid_tickers}
        return equal_w, fund_raw_eq, sharpe_raw, None

    # Llegim els pesos bruts del CSV
    weight_map = {}
    for _, row in df_final.iterrows():
        tk = str(row[ticker_col]).strip().upper()
        raw = row[weight_col_used]
        try:
            val_str = str(raw).replace(",", ".").replace("%", "").strip()
            if not val_str or val_str.lower() in ("nan", "none", "<na>"):
                val = 0.0
            else:
                val = float(val_str)
        except (ValueError, TypeError):
            val = 0.0
        weight_map[tk] = max(val, 0.0)

    # Detecta format automàticament:
    #  - Si la suma total és > 2 → format percentual (2.95 = 2.95%)
    #  - Si la suma total és ≤ 2 → format fraccional (0.0295 = 2.95%)
    csv_total = sum(weight_map.values())
    is_percent = csv_total > 2.0

    # fund_raw conté el PES EN PERCENTATGE (per mostrar a la taula, 2.95 = 2.95%)
    # weights conté el PES EN FRACCIÓ (per multiplicar pel capital, 0.0295)
    fund_raw = {}
    weights = {}
    for t in valid_tickers:
        w_csv = weight_map.get(t.upper(), 0.0)
        if is_percent:
            fund_raw[t] = w_csv          # ja ve en %
            weights[t] = w_csv / 100.0
        else:
            fund_raw[t] = w_csv * 100.0  # passa a %
            weights[t] = w_csv

    # Si tots els pesos dels actius vàlids són 0 → fallback equal-weight
    if sum(weights.values()) <= 0:
        fund_raw_eq = {t: 100.0 / n for t in valid_tickers}
        return equal_w, fund_raw_eq, sharpe_raw, weight_col_used

    # NO renormalitzem: els pesos mostrats a Backtest = pesos d'Informació empresa
    # (si hi ha actius no vàlids, el seu capital simplement queda en cash)
    return weights, fund_raw, sharpe_raw, weight_col_used


# ─────────────────────────────────────────────────────────────
# TAB 2 — BACKTEST CARTERA
# ─────────────────────────────────────────────────────────────
def render_backtest_cartera(
    hist_path: Path,
    df_fund: pd.DataFrame,
    df_final: pd.DataFrame | None = None,
) -> None:
    apply_global_styles()
    render_page_header(
        "Backtest Cartera",
        "Capital assignat segons scoring fonamental · 100% del capital a cada compra · Descàrregues CSV."
    )

    # ─── Versió + botó d'esborrament del cache ───
    # IMPORTANT: si has actualitzat el codi i veus valors estranys, prem
    # aquest botó. Streamlit guarda el cache al disc i pot reutilitzar
    # entrades de versions anteriors.
    ver_c1, ver_c2 = st.columns([5, 1])
    with ver_c1:
        st.markdown(
            "<div style='font-size:.72rem;color:#64748b;padding:4px 0;'>"
            "🔖 Codi <code>cartera v2.0</code> · Si veus valors iguals per actius diferents, "
            "prem el botó <b>'🧹 Esborrar cache'</b> →"
            "</div>",
            unsafe_allow_html=True,
        )
    with ver_c2:
        if st.button("🧹 Esborrar cache", key="clear_cache_btn", use_container_width=True,
                     help="Esborra el cache de Streamlit. Útil si has actualitzat el codi i veus dades antigues."):
            st.cache_data.clear()
            st.success("✓ Cache esborrat. Recarrega per refrescar.")
            st.rerun()

    if not hist_path.exists():
        st.error(f"Carpeta no trobada: `{hist_path}`")
        return

    companies = (
        df_fund[["Ticker", "Companyia"]]
        .dropna(subset=["Ticker"])
        .drop_duplicates(subset=["Ticker"])
        .reset_index(drop=True)
    )

    if companies.empty:
        st.warning("No hi ha empreses disponibles.")
        return

    any_sample = None
    for _, _row in companies.iterrows():
        tk = str(_row["Ticker"])
        cn = str(_row["Companyia"]) if "Companyia" in companies.columns else None
        temp = load_ohlc(tk, hist_path, company_name=cn)
        if temp is not None and not temp.empty:
            any_sample = temp
            break

    if any_sample is None:
        st.warning("No s'han trobat fitxers històrics vàlids.")
        return

    d_min = any_sample["Date"].min().date()
    d_max = any_sample["Date"].max().date()
    # Per defecte: arrencar al període d'estudi del treball (clampat al
    # rang disponible). Les dades anteriors a STUDY_START_DATE NO entren
    # al backtest: queden com a warm-up dels indicadors.
    default_from = max(min(STUDY_START_DATE, d_max), d_min)
    default_to   = max(min(STUDY_END_DATE,   d_max), d_min)

    # ── UI: ponderació de capital ────────────────────────
    wcol1, wcol_lbl = st.columns([1, 2])
    with wcol1:
        use_fundamental = st.checkbox(
            "📊 Ponderar per classificació fonamental",
            value=True,
            key="pf_use_fund",
            help="Assigna capital a cada actiu segons el pes que té a la classificació fonamental "
                 "(el mateix valor que apareix a 'Informació cartera' → 'Classificació Final'). "
                 "Si es desactiva, s'aplica equal-weight (1/N).",
        )
    with wcol_lbl:
        mode_lbl = "Pes de la classificació fonamental" if use_fundamental else "Equal-weight (1/N)"
        st.markdown(
            f"<div style='padding:8px 14px;background:#eff6ff;border:1px solid #bfdbfe;"
            f"border-radius:8px;font-size:.82rem;color:#1d4ed8;font-weight:600;'>"
            f"Mode actiu: {mode_lbl}</div>",
            unsafe_allow_html=True,
        )

    # ── Controls inline: execució + position sizing (sense expander) ──
    st.markdown(
        "<div style='margin-top:6px;font-size:.72rem;color:#64748b;font-weight:600;"
        "text-transform:uppercase;letter-spacing:.06em;'>⏱️ Execució d'ordres</div>",
        unsafe_allow_html=True,
    )
    exec_c1_pf, exec_c2_pf = st.columns([1, 2])
    with exec_c1_pf:
        delay_bars_pf = st.select_slider(
            "Barres de confirmació:",
            options=[0, 1, 2],
            value=0,
            key="delay_bars_pf",
            format_func=lambda x: f"{x} barra(s)" + ("  [clàssic]" if x == 0 else ("  [realista]" if x == 1 else "  [conservador]")),
            help="Nombre de barres de retard entre la detecció del senyal i l'execució de l'ordre. "
                 "Amb retard > 0 s'elimina qualsevol biaix de look-ahead.",
        )
    with exec_c2_pf:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        st.caption(
            "💡 S'aplica a tots els 30 actius de la cartera."
        )

    # ── Comissions per a comparació justa Estratègia vs B&H ──
    st.markdown(
        "<div style='margin-top:12px;font-size:.72rem;color:#94a3b8;font-weight:600;"
        "text-transform:uppercase;letter-spacing:.06em;'>💶 Costos de transacció</div>",
        unsafe_allow_html=True,
    )
    fee_c1_pf, fee_c2_pf, fee_c3_pf = st.columns([1, 1, 1])
    with fee_c1_pf:
        fee_pct_pf = st.slider(
            "Comissió per operació (%):",
            min_value=0.0, max_value=2.0, value=0.25, step=0.05,
            key="fee_pct_pf",
            help="S'aplica a compra i venda (Estratègia + B&H + ETF MSCI World).",
        )
    with fee_c2_pf:
        bh_maint_pct_pf = st.slider(
            "Manteniment anual B&H (%):",
            min_value=0.0, max_value=2.0, value=0.0, step=0.05,
            key="bh_maint_pf",
            help="Cost de custòdia anual (prorratejat per dies) aplicat només al B&H.",
        )
    with fee_c3_pf:
        msci_ter_pct_pf = st.slider(
            "TER anual MSCI World (%):",
            min_value=0.0, max_value=2.0, value=0.20, step=0.05,
            key="msci_ter_pf",
            help="Total Expense Ratio anual de l'ETF que rèplica el MSCI World "
                 "(p.ex. iShares Core MSCI World: ~0.20%). Prorratejat per dies.",
        )

    # ── Selectors de període + capital com a targetes ────
    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        st.markdown(
            '<div style="font-size:.68rem;color:#94a3b8;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">📅 Des de</div>',
            unsafe_allow_html=True,
        )
        date_from = st.date_input(
            "Des de:", value=default_from, min_value=d_min, max_value=d_max,
            key="pf_from", label_visibility="collapsed",
        )
    with c2:
        st.markdown(
            '<div style="font-size:.68rem;color:#94a3b8;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">📅 Fins a</div>',
            unsafe_allow_html=True,
        )
        date_to = st.date_input(
            "Fins a:", value=default_to, min_value=d_min, max_value=d_max,
            key="pf_to", label_visibility="collapsed",
        )
    with c3:
        st.markdown(
            '<div style="font-size:.68rem;color:#94a3b8;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">💰 Capital inicial cartera (€)</div>',
            unsafe_allow_html=True,
        )
        capital_total = st.number_input(
            "Capital inicial cartera (€):",
            min_value=1_000.0, max_value=100_000_000.0,
            value=100_000.0, step=5_000.0, format="%.2f",
            key="pf_capital", label_visibility="collapsed",
        )

    if date_from >= date_to:
        st.warning("La data d'inici ha de ser anterior a la data final.")
        return

    # ── Pre-passada: validem actius i recollim retorns ───
    # NOTA: guardem TANT df_ohlc (sèrie completa, per al warm-up dels
    # indicadors) com df_period (retallat al període d'estudi, per al
    # càlcul de retorns diaris del pes Sharpe).
    valid_data = []      # (ticker, company, df_ohlc, df_period, daily_returns)
    diag_rows = []       # Diagnòstic de TOTS els tickers (inclosos descartats)
    total_tickers = len(companies)

    with st.spinner(f"Validant {total_tickers} actius…"):
        for _, row in companies.iterrows():
            ticker = str(row["Ticker"]).strip()
            company = str(row["Companyia"]).strip()

            df_ohlc = load_ohlc(ticker, hist_path, company_name=company)
            if df_ohlc is None or df_ohlc.empty:
                diag_rows.append({
                    "Ticker": ticker,
                    "Companyia": company,
                    "Estat": "❌ Fitxer OHLC no trobat",
                    "Sessions al període": 0,
                })
                continue

            mask = (df_ohlc["Date"].dt.date >= date_from) & (df_ohlc["Date"].dt.date <= date_to)
            df_period = df_ohlc.loc[mask].reset_index(drop=True)
            n_sessions = len(df_period)

            if n_sessions < 30:
                diag_rows.append({
                    "Ticker": ticker,
                    "Companyia": company,
                    "Estat": f"⚠️ Dades insuficients (mínim 30 sessions)",
                    "Sessions al període": n_sessions,
                })
                continue

            daily_rets = df_period["Close"].pct_change().dropna()
            valid_data.append((ticker, company, df_ohlc, df_period, daily_rets))
            diag_rows.append({
                "Ticker": ticker,
                "Companyia": company,
                "Estat": "✓ OK",
                "Sessions al període": n_sessions,
            })

    n_ok = len(valid_data)
    n_total = len(diag_rows)
    n_desc = n_total - n_ok

    # Barra de resum + diagnòstic si falten actius
    if n_desc > 0:
        st.markdown(
            f"<div style='padding:10px 14px;background:#fef3c7;border:1px solid #fcd34d;"
            f"border-radius:8px;font-size:.83rem;color:#92400e;margin-bottom:10px;'>"
            f"⚠️ <b>{n_ok} de {n_total}</b> actius processats. "
            f"<b>{n_desc}</b> actiu(s) descartat(s) — consulta el diagnòstic per detalls."
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='padding:10px 14px;background:#f0fdf4;border:1px solid #bbf7d0;"
            f"border-radius:8px;font-size:.83rem;color:#15803d;margin-bottom:10px;'>"
            f"✓ <b>Tots els {n_total} actius</b> carregats correctament."
            f"</div>",
            unsafe_allow_html=True,
        )

    # Taula de diagnòstic (sempre disponible, expandida si hi ha descartats)
    df_diag = pd.DataFrame(diag_rows)
    with st.expander(f"🔍 Diagnòstic dels {n_total} actius (expandeix per veure detalls)",
                     expanded=(n_desc > 0)):
        render_table(
            "Estat de càrrega per actiu",
            df_diag,
            subtitle="Llista completa d'actius de la cartera amb l'estat de càrrega al període seleccionat.",
            height_class="short",
        )
        csv_diag = _df_to_csv_bytes(df_diag)
        st.download_button(
            label="📥 Descarregar diagnòstic (CSV)",
            data=csv_diag,
            file_name=f"diagnostic_cartera_{date_from}_{date_to}.csv",
            mime="text/csv",
            key="dl_diag",
        )

    if not valid_data:
        st.warning("Cap empresa amb dades suficients en el període seleccionat.")
        return

    # ── Càlcul de pesos ──────────────────────────────────
    valid_tickers = [v[0] for v in valid_data]
    returns_dict = {v[0]: v[4] for v in valid_data}  # daily_rets ara és v[4] (era v[3])
    weights, fund_raw, sharpe_raw, weight_col_used = _compute_portfolio_weights(
        valid_tickers, df_final, returns_dict, use_fundamental
    )

    # Avís sobre la columna emprada
    if use_fundamental:
        if weight_col_used is not None:
            st.markdown(
                f"<div style='padding:6px 12px;background:#f0fdf4;border:1px solid #bbf7d0;"
                f"border-radius:8px;font-size:.78rem;color:#15803d;margin-bottom:8px;'>"
                f"✓ Pes extret de la columna <code>{weight_col_used}</code> a "
                f"<code>Top30_CLASSIFICACIO_FINAL.csv</code> — els valors coincideixen amb 'Informació cartera'.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='padding:6px 12px;background:#fef3c7;border:1px solid #fcd34d;"
                "border-radius:8px;font-size:.78rem;color:#92400e;margin-bottom:8px;'>"
                "⚠️ No s'ha pogut identificar la columna de pes a <code>Top30_CLASSIFICACIO_FINAL.csv</code>. "
                "S'ha aplicat equal-weight (1/N) com a fallback."
                "</div>",
                unsafe_allow_html=True,
            )

    # ── Backtest per actiu ───────────────────────────────
    rows = []
    per_asset_data = {}   # {ticker: {"company":..., "dataset":..., "result":..., "cfg": StrategyConfig}}

    # ── Configuració fiscal vigent ─────────────────────────────────────────
    # La llegim AQUÍ, abans del bucle, per poder calcular l'impost orientatiu
    # PER ACTIU (com a "única inversió del contribuent") i incloure'l a
    # df_res. Això permet que la taula "Detall per actiu" mostri columnes
    # de Brut/Net/Impostos coherents amb el check de fiscalitat. El càlcul
    # fiscalment vàlid (base de cartera global) es continua fent més avall
    # a partir de pf_all_sales i s'usa als KPIs i taula comparativa.
    tax_cfg_pre = tax_config_from_state()

    with st.spinner("Executant estratègia actiu per actiu…"):
        for ticker, company, df_ohlc, df_period, _ in valid_data:
            w = float(weights.get(ticker, 0.0))
            cap_i = capital_total * w
            fund_sc = float(fund_raw.get(ticker, 0.0))
            sr_sc = float(sharpe_raw.get(ticker, 0.0))

            if cap_i <= 0 or w <= 0:
                # Actiu exclòs per pes 0
                rows.append({
                    "Ticker": ticker,
                    "Companyia": company,
                    "Pes (%)": 0.0,
                    "Pes fonam. (%)": round(fund_sc, 2),
                    "Sharpe anual": round(sr_sc, 3),
                    "Capital inicial": 0.0,
                    "Capital final estratègia": 0.0,
                    "Retorn estratègia (%)": 0.0,
                    "Retorn estratègia net (%)": 0.0,
                    "Capital final B&H": 0.0,
                    "Retorn B&H (%)": 0.0,
                    "Retorn B&H net (%)": 0.0,
                    "Operacions": 0,
                    "Comissions (€)": 0.0,
                    "Impostos IRPF (€)": 0.0,
                    "Impostos IRPF B&H (€)": 0.0,
                    "Fracció mitjana (%)": 0.0,
                    "Taxa encert (%)": 0.0,
                    "Max DD (%)": 0.0,
                })
                continue

            cfg_i = StrategyConfig(
                capital_inicial=cap_i,
                entry_delay_bars=int(delay_bars_pf),
                fee_buy_pct=float(fee_pct_pf) / 100.0,
                fee_sell_pct=float(fee_pct_pf) / 100.0,
                bh_annual_maintenance_pct=float(bh_maint_pct_pf) / 100.0,
            )
            # WARM-UP + RESTRICCIÓ:
            # Es passa df_ohlc COMPLET (no df_period) perquè els indicadors
            # tinguin un buffer de WARMUP_BUFFER_DAYS dies abans de date_from.
            # La funció retorna el dataset ja retallat a [date_from, date_to];
            # run_strategy_backtest no veu cap fila de warm-up i, per tant,
            # NO pot generar cap operació fora del període d'estudi.
            # La part costosa (indicadors) està cachejada via
            # _build_indicators_cached_v2 dins de build_strategy_dataset.
            ds = build_strategy_dataset_with_warmup(
                df_ohlc, cfg_i,
                trade_start=date_from, trade_end=date_to,
                warmup_days=WARMUP_BUFFER_DAYS,
            )
            res = run_strategy_backtest(ds, cfg_i)

            # Guardem per al reproductor
            per_asset_data[ticker] = {
                "company": company,
                "dataset": ds,
                "result": res,
            }

            # ── Impost orientatiu PER ACTIU (com a "única inversió") ──────
            # Útil per veure la contribució individual i poder mostrar
            # Brut/Net per fila. NO és el càlcul fiscalment vàlid (la base
            # de l'estalvi és de cartera), però quadra qualitativament i
            # permet ordenar/filtrar pel cost fiscal de cada posició.
            sales_i = sales_from_trades(res["trades"], ticker)
            tax_summ_i = compute_tax_summary(sales_i, tax_cfg_pre)
            tax_i = tax_summ_i.total_tax
            # B&H individual: una venda al final del període
            bh_pnl_i = float(res["bh_capital_final"]) - float(res["capital_inicial"])
            bh_sale_i = [TaxableSale(
                ticker=ticker,
                sell_date=_to_date(str(date_to)),
                buy_date=_to_date(str(date_from)),
                pnl=bh_pnl_i,
            )]
            bh_tax_i = compute_tax_summary(bh_sale_i, tax_cfg_pre).total_tax
            # Retorns nets en %
            ret_strat_net_i = (
                (float(res["capital_final"]) - tax_i) / float(res["capital_inicial"]) - 1.0
            ) * 100.0 if res["capital_inicial"] > 0 else 0.0
            ret_bh_net_i = (
                (float(res["bh_capital_final"]) - bh_tax_i) / float(res["capital_inicial"]) - 1.0
            ) * 100.0 if res["capital_inicial"] > 0 else 0.0

            rows.append({
                "Ticker": ticker,
                "Companyia": company,
                "Pes (%)": round(w * 100, 2),
                "Pes fonam. (%)": round(fund_sc, 2),
                "Sharpe anual": round(sr_sc, 3),
                "Capital inicial": round(cap_i, 2),
                "Capital final estratègia": res["capital_final"],
                "Retorn estratègia (%)": res["strat_total"],
                "Retorn estratègia net (%)": round(ret_strat_net_i, 2),
                "Capital final B&H": res["bh_capital_final"],
                "Retorn B&H (%)": res["bh_return"],
                "Retorn B&H net (%)": round(ret_bh_net_i, 2),
                "Operacions": res["n_trades"],
                "Comissions (€)": res.get("total_fees", 0.0),
                "Impostos IRPF (€)": round(tax_i, 2),
                "Impostos IRPF B&H (€)": round(bh_tax_i, 2),
                "Taxa encert (%)": res["win_rate"],
                "Max DD (%)": res["max_dd"],
            })

    if not rows:
        st.warning("No s'han pogut generar resultats per a la cartera.")
        return

    df_res = pd.DataFrame(rows).sort_values("Pes (%)", ascending=False).reset_index(drop=True)

    # ── Agregats ─────────────────────────────────────────
    # Capital no invertit (actius exclosos) es queda en efectiu → contribueix al valor final igual al nominal
    capital_invertit = df_res["Capital inicial"].sum()
    capital_no_invertit = capital_total - capital_invertit

    strat_cap_final = df_res["Capital final estratègia"].sum() + capital_no_invertit
    # Per B&H calculem què hauria fet si tot s'hagués col·locat amb els mateixos pesos
    bh_cap_final = df_res["Capital final B&H"].sum() + capital_no_invertit

    strat_ret = (strat_cap_final / capital_total - 1.0) * 100.0
    bh_ret = (bh_cap_final / capital_total - 1.0) * 100.0
    diff = strat_ret - bh_ret
    total_trades = int(df_res["Operacions"].sum())
    # Comissions acumulades de TOTA la cartera (suma per actiu). Es recalcula
    # automàticament en canviar el % de comissió perquè cada res["total_fees"]
    # depèn de fee_buy_pct / fee_sell_pct.
    total_fees_pf = float(df_res["Comissions (€)"].sum())
    total_fees_pf_pct = (total_fees_pf / capital_total * 100.0) if capital_total > 0 else 0.0

    # ── FISCALITAT: impost agregat de la cartera ───────────────────────────
    # La base de l'estalvi de l'IRPF es calcula a nivell de CARTERA (suma de
    # guanys i pèrdues de tots els actius d'un mateix any), no actiu per
    # actiu. Per això recollim aquí totes les vendes de tots els actius i
    # liquidem una sola vegada. tax_config_from_state() llegeix els controls
    # de la pestanya Fiscalitat: si l'usuari hi canvia un tram, l'impost
    # d'aquests KPIs es recalcula automàticament a la propera execució.
    tax_cfg = tax_config_from_state()
    pf_all_sales: list[TaxableSale] = []
    pf_bh_sales: list[TaxableSale] = []
    for tk, d in per_asset_data.items():
        res_d = d["result"]
        for t in res_d["trades"]:
            try:
                pf_all_sales.append(TaxableSale(
                    ticker=tk,
                    sell_date=_to_date(t["Sortida"]),
                    buy_date=_to_date(t["Entrada"]),
                    pnl=float(t.get("Guany/Perdua", 0.0)),
                ))
            except Exception:
                continue
        # B&H: una única transmissió al final del període
        try:
            pf_bh_sales.append(TaxableSale(
                ticker=tk,
                sell_date=_to_date(str(date_to)),
                buy_date=_to_date(str(date_from)),
                pnl=float(res_d["bh_capital_final"]) - float(res_d["capital_inicial"]),
            ))
        except Exception:
            pass

    pf_tax_summary = compute_tax_summary(pf_all_sales, tax_cfg)
    pf_bh_tax_summary = compute_tax_summary(pf_bh_sales, tax_cfg)
    pf_total_tax = pf_tax_summary.total_tax
    pf_bh_total_tax = pf_bh_tax_summary.total_tax

    # Capitals i rendiments NETS d'impostos
    strat_cap_final_net = strat_cap_final - pf_total_tax
    bh_cap_final_net = bh_cap_final - pf_bh_total_tax
    strat_ret_net = (strat_cap_final_net / capital_total - 1.0) * 100.0
    bh_ret_net = (bh_cap_final_net / capital_total - 1.0) * 100.0
    diff_net = strat_ret_net - bh_ret_net

    # Mitjanes ponderades pel pes (només actius invertits)
    invested = df_res[df_res["Pes (%)"] > 0].copy()
    n_invested = len(invested)
    n_excluded = len(df_res) - n_invested

    if not invested.empty:
        w_arr = invested["Pes (%)"].to_numpy() / 100.0
        w_arr = w_arr / w_arr.sum() if w_arr.sum() > 0 else w_arr
        avg_winrate = float((invested["Taxa encert (%)"].to_numpy() * w_arr).sum())
        avg_maxdd = float((invested["Max DD (%)"].to_numpy() * w_arr).sum())
    else:
        avg_winrate = 0.0
        avg_maxdd = 0.0

    def card(label, value, color="#f1f5f9"):
        return (
            f'<div style="flex:1;min-width:170px;background:#111111;border:1px solid #2a2a2a;'
            f'border-radius:12px;padding:14px 16px;">'
            f'<div style="font-size:.68rem;color:#94a3b8;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:6px;">{label}</div>'
            f'<div style="font-family:\'DM Mono\',monospace;font-size:1.08rem;font-weight:700;color:{color};">{value}</div>'
            f'</div>'
        )

    assets_lbl = f"{n_invested}/{n_total}" + (f" <span style='color:#94a3b8;font-size:.85em;'>(+{n_excluded} excl.)</span>" if n_excluded > 0 else "")

    # Si la fiscalitat és activa, els KPIs principals mostren valors NETS
    # d'impostos i s'afegeix una targeta amb l'impost total. Si no, es
    # mostren els valors bruts de sempre.
    if tax_cfg.enabled:
        strat_show, bh_show, diff_show = strat_ret_net, bh_ret_net, diff_net
        ret_suffix = " <span style='color:#94a3b8;font-size:.7em;'>net</span>"
    else:
        strat_show, bh_show, diff_show = strat_ret, bh_ret, diff
        ret_suffix = ""

    fiscal_card = (
        card("Impostos IRPF", f"{pf_total_tax:,.2f}€", "#f59e0b")
        if tax_cfg.enabled else ""
    )

    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 18px 0;">'
        + card("Estratègia cartera" + ret_suffix, f"{strat_show:+.2f}%", "#16a34a" if strat_show >= 0 else "#dc2626")
        + card("Buy & Hold cartera" + ret_suffix, f"{bh_show:+.2f}%", "#16a34a" if bh_show >= 0 else "#dc2626")
        + card("Diferència", f"{diff_show:+.2f}%", "#16a34a" if diff_show >= 0 else "#dc2626")
        + card("Actius invertits", assets_lbl)
        + card("Operacions totals", str(total_trades))
        + card("Comissions totals", f"{total_fees_pf:,.2f}€", "#f59e0b")
        + fiscal_card
        + card("Taxa encert pond.", f"{avg_winrate:.1f}%", "#16a34a" if avg_winrate >= 50 else "#dc2626")
        + card("Max DD pond.", f"{avg_maxdd:.2f}%", "#dc2626")
        + '</div>',
        unsafe_allow_html=True,
    )
    if tax_cfg.enabled:
        st.caption(
            "🧾 Rendiments NETS d'IRPF (base de l'estalvi). El detall de "
            "la liquidació és a la pestanya **Fiscalitat**."
        )

    # ── 4 Sub-pestanyes: Resultat per actiu / Reproducció / Timeline / Corba ──
    if per_asset_data:
        # ════════════════════════════════════════════════════════
        # CÀLCULS COMPARTITS (necessaris per a múltiples sub-pestanyes)
        # Es calculen UN COP aquí perquè 'Taula completa' i 'Corba de capital'
        # comparteixen aquestes dades.
        # ════════════════════════════════════════════════════════

        # ── Equity agregada de la cartera ─────────
        # IMPORTANT: per evitar discontinuïtats verticals quan un actiu té
        # dades que comencen més tard (ex: una empresa que es va llistar el
        # 2018 dins un període 2014→avui), assegurem que CADA actiu
        # contribueix una valoració constant (capital_inicial) abans de la
        # seva primera data, i el seu darrer valor després de l'última data.
        # Així la suma sobre el conjunt de dates és continua i no fa salts.

        # 1) Recollim totes les dates únicament de la unió de tots els actius
        pf_dates_set = set()
        for tk, d in per_asset_data.items():
            for p in d["result"]["equity"]:
                pf_dates_set.add(p["time"])
        pf_dates_sorted = sorted(pf_dates_set)

        # 2) Per cada actiu, pre-omplim un map data→valor cobrint TOTES les dates:
        #    • Abans de l'inici → capital_inicial (no invertit encara)
        #    • Durant l'activitat → valor d'equity real
        #    • Després del final → últim valor conegut (forward-fill)
        cash_non_invested = float(capital_no_invertit)  # actius exclosos
        pf_equity_map = {d: 0.0 for d in pf_dates_sorted}

        for tk, d in per_asset_data.items():
            cap_init_asset = float(d["result"]["capital_inicial"])
            equity_pts = d["result"]["equity"]
            if not equity_pts:
                # No hi ha cap valoració → l'actiu manté el capital inicial sempre
                for date in pf_dates_sorted:
                    pf_equity_map[date] += cap_init_asset
                continue

            # Diccionari: data → valor d'aquest actiu
            asset_eq = {p["time"]: float(p["value"]) for p in equity_pts}
            asset_dates_sorted = sorted(asset_eq.keys())
            first_date = asset_dates_sorted[0]
            last_date = asset_dates_sorted[-1]
            last_known_value = cap_init_asset

            for date in pf_dates_sorted:
                if date < first_date:
                    # L'actiu encara no ha començat → val el seu capital inicial
                    pf_equity_map[date] += cap_init_asset
                elif date in asset_eq:
                    # Tenim valoració exacta aquest dia
                    last_known_value = asset_eq[date]
                    pf_equity_map[date] += last_known_value
                elif date > last_date:
                    # Després de l'última dada → mantenim l'últim valor (forward-fill)
                    pf_equity_map[date] += last_known_value
                else:
                    # Forat enmig (cap d'aquests casos en datasets normals) → últim
                    pf_equity_map[date] += last_known_value

        pf_equity_points = [
            {"time": d, "value": round(pf_equity_map[d] + cash_non_invested, 4)}
            for d in pf_dates_sorted
        ]

        # ── Equity B&H agregada de la cartera (NET, costos inclosos) ─
        # Replica la mateixa agregació que `pf_equity_points` però usant
        # `result["bh_equity"]` (corba B&H per dia NET) en lloc de
        # `result["equity"]` (estratègia). Així garantim que la taula
        # comparativa i el gràfic mostren un B&H amb els mateixos costos
        # (fee, slippage, manteniment) que els KPIs del top:
        #
        #   pf_bh_equity_points[0]  = sum(cap_init_asset) + cash       = capital_total
        #   pf_bh_equity_points[-1] = sum(bh_capital_final) + cash     ← coincideix
        #                                                                amb KPI
        #
        # Substitueix l'antic `bh_prices_df` (índex sintètic de preus
        # SENSE costos), que generava la discrepància que veies entre
        # KPI ("Buy & Hold Cartera") i taula ("Buy & Hold (cartera)").
        pf_bh_equity_map = {d: 0.0 for d in pf_dates_sorted}

        for tk, d in per_asset_data.items():
            cap_init_asset = float(d["result"]["capital_inicial"])
            bh_pts = d["result"].get("bh_equity", []) or []
            if not bh_pts:
                # Sense corba B&H → l'actiu manté el capital inicial sempre
                for date in pf_dates_sorted:
                    pf_bh_equity_map[date] += cap_init_asset
                continue

            asset_bh = {p["time"]: float(p["value"]) for p in bh_pts}
            asset_dates_sorted = sorted(asset_bh.keys())
            first_date_bh = asset_dates_sorted[0]
            last_date_bh = asset_dates_sorted[-1]
            last_known_bh = cap_init_asset

            for date in pf_dates_sorted:
                if date < first_date_bh:
                    pf_bh_equity_map[date] += cap_init_asset
                elif date in asset_bh:
                    last_known_bh = asset_bh[date]
                    pf_bh_equity_map[date] += last_known_bh
                elif date > last_date_bh:
                    pf_bh_equity_map[date] += last_known_bh
                else:
                    pf_bh_equity_map[date] += last_known_bh

        pf_bh_equity_points = [
            {"time": d, "value": round(pf_bh_equity_map[d] + cash_non_invested, 4)}
            for d in pf_dates_sorted
        ]

        # ── Desat per a la pestanya FISCALITAT ─────────────────────────────
        # La pestanya Fiscalitat no recalcula res: llegeix aquest paquet de
        # st.session_state. Hi guardem, per cada actiu, les operacions (per
        # derivar-ne les vendes imposables), les corbes d'equity (per aplicar
        # l'impost) i els capitals. També les corbes agregades de la cartera
        # i el període, perquè la fiscalitat del B&H necessita la data de
        # transmissió final. Es desa CADA cop que es recalcula el backtest,
        # de manera que si l'usuari canvia paràmetres, la fiscalitat es
        # refresca a la propera visita de la pestanya.
        st.session_state["fiscal_data"] = {
            "period": [str(date_from), str(date_to)],
            "capital_total": float(capital_total),
            "pf_equity_points": pf_equity_points,
            "pf_bh_equity_points": pf_bh_equity_points,
            "assets": [
                {
                    "ticker": tk,
                    "company": d["company"],
                    "trades": d["result"]["trades"],
                    "equity": d["result"]["equity"],
                    "bh_equity": d["result"].get("bh_equity", []),
                    "capital_inicial": float(d["result"]["capital_inicial"]),
                    "capital_final": float(d["result"]["capital_final"]),
                    "bh_capital_final": float(d["result"]["bh_capital_final"]),
                    "period": [str(date_from), str(date_to)],
                }
                for tk, d in per_asset_data.items()
            ],
        }

        # ── Preus sintètics per B&H ponderat de la cartera ─
        # Per cada actiu, calculem el seu preu normalitzat (Close / first_close)
        # i el ponderem pel seu pes a la cartera. Sumant les contribucions
        # ponderades obtenim un índex sintètic.
        # IMPORTANT: per evitar discontinuïtats verticals (un actiu que entra
        # amb dades a meitat del període), assignem 1.0 (preu inicial) a totes
        # les dates anteriors a la seva primera dada — així la seva contribució
        # ponderada és constant pre-inici. Mateixa lògica al final.
        bh_dates_set = set()
        for tk, d in per_asset_data.items():
            for _, prow in d["dataset"].dropna(subset=["Close"]).iterrows():
                bh_dates_set.add(str(prow["Date"])[:10])
        bh_dates_all = sorted(bh_dates_set)

        if bh_dates_all:
            bh_norm_sum = {dt: 0.0 for dt in bh_dates_all}
            for tk, d in per_asset_data.items():
                ds_asset = d["dataset"].dropna(subset=["Close"])
                if ds_asset.empty:
                    continue
                first_close = float(ds_asset["Close"].iloc[0])
                if first_close <= 0:
                    continue
                w = float(df_res[df_res["Ticker"] == tk]["Pes (%)"].iloc[0]) / 100.0 if tk in df_res["Ticker"].values else 0.0
                if w <= 0:
                    continue

                # Map data → close normalitzat per aquest actiu
                asset_norm = {
                    str(prow["Date"])[:10]: float(prow["Close"]) / first_close
                    for _, prow in ds_asset.iterrows()
                }
                asset_dates = sorted(asset_norm.keys())
                first_d = asset_dates[0]
                last_d = asset_dates[-1]
                last_val = 1.0

                for dt in bh_dates_all:
                    if dt < first_d:
                        # No iniciat → contribució = 1.0 × pes (manté el capital intacte)
                        bh_norm_sum[dt] += 1.0 * w
                    elif dt in asset_norm:
                        last_val = asset_norm[dt]
                        bh_norm_sum[dt] += last_val * w
                    elif dt > last_d:
                        bh_norm_sum[dt] += last_val * w
                    else:
                        # Forat enmig (raríssim) → forward-fill
                        bh_norm_sum[dt] += last_val * w

            # Pes total dels actius invertits (pot ser <1.0 si hi ha actius exclosos).
            # Afegim la part en cash (1.0 constant ponderat pel seu pes).
            cash_weight = max(0.0, 1.0 - sum(
                float(df_res[df_res["Ticker"] == tk]["Pes (%)"].iloc[0]) / 100.0
                for tk in per_asset_data.keys()
                if tk in df_res["Ticker"].values
            ))

            # bh_norm_sum ja inclou les contribucions ponderades dels actius;
            # afegim el cash que no varia (contribueix cash_weight a tots els dies).
            for dt in bh_dates_all:
                bh_norm_sum[dt] += cash_weight

            # Normalitzem perquè el primer dia sigui exactament 1.0
            first_total = bh_norm_sum[bh_dates_all[0]]
            if first_total > 0:
                bh_prices_df = pd.DataFrame([
                    {"Date": dt, "Close": bh_norm_sum[dt] / first_total}
                    for dt in bh_dates_all
                ])
            else:
                bh_prices_df = pd.DataFrame(columns=["Date", "Close"])
        else:
            bh_prices_df = pd.DataFrame(columns=["Date", "Close"])

        st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
        pb_sub0, pb_sub_table, pb_sub1, pb_sub2, pb_sub3 = st.tabs([
            "📊  Resultat per actiu",
            "📋  Taula completa (comparativa)",
            "🎬  Reproducció individual",
            "📜  Línia temporal de la cartera",
            "📈  Corba de capital (vs MSCI World)",
        ])

        # ── Sub-tab 0: Resultat per actiu (cards + taula + mini-corbes) ──
        with pb_sub0:
            st.markdown(
                "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:10px;line-height:1.5;'>"
                "Targetes resum dels 30 actius amb pes, retorns, operacions i max DD. "
                "Prem el botó <b>📈 Mini-corba</b> de qualsevol actiu per veure la seva "
                "evolució individual (base 100 vs Buy &amp; Hold)."
                "</div>",
                unsafe_allow_html=True,
            )

            # ── Targetes individuals amb logo + mini-corba expandible ──
            # Tri tickers per pes descendent per veure primer els més importants
            sorted_tickers = sorted(
                per_asset_data.keys(),
                key=lambda tk: df_res[df_res["Ticker"] == tk]["Pes (%)"].iloc[0] if tk in df_res["Ticker"].values else 0,
                reverse=True,
            )

            # Construïm una sola pàgina HTML amb totes les targetes en grid.
            # Cada targeta és un <details> (accordion natiu) amb la mini-corba
            # SVG inline dins (evita haver de crear un iframe per cada una).
            card_blocks = []
            for tk in sorted_tickers:
                info = per_asset_data[tk]
                row_match = df_res[df_res["Ticker"] == tk]
                if row_match.empty:
                    continue
                r = row_match.iloc[0]
                pes = float(r["Pes (%)"])
                ret_strat = float(r["Retorn estratègia (%)"])
                ret_bh = float(r["Retorn B&H (%)"])
                n_ops = int(r["Operacions"])
                max_dd = float(r["Max DD (%)"])
                winrate = float(r["Taxa encert (%)"])
                fees_asset = float(r["Comissions (€)"]) if "Comissions (€)" in r else 0.0

                strat_col_c = "#10b981" if ret_strat >= 0 else "#ef4444"
                bh_col_c = "#3b82f6" if ret_bh >= 0 else "#2563eb"
                diff = ret_strat - ret_bh
                diff_col = "#10b981" if diff >= 0 else "#ef4444"
                diff_sign = "+" if diff >= 0 else ""

                # Mini-corba com a SVG inline (sense iframe ⇒ lleuger i clicable)
                mini_svg = _build_mini_equity_svg(
                    equity_points=info["result"]["equity"],
                    capital_inicial=info["result"]["capital_inicial"],
                    prices_df=info["dataset"][["Date", "Close"]],
                    width=252,
                    height=120,
                )

                # Logo (cercle negre amb anell subtil)
                logo_snippet = _logo_html(tk, info["company"], size=40)

                card_blocks.append(f"""
<details class="asset-card">
  <summary class="asset-card-head">
    {logo_snippet}
    <div class="asset-card-info">
      <div class="asset-card-tk">{tk}</div>
      <div class="asset-card-name">{info['company']}</div>
    </div>
    <div class="asset-card-weight">{pes:.2f}%</div>
    <div class="asset-card-chevron">▾</div>
  </summary>

  <div class="asset-card-body">
    <div class="asset-card-kpis">
      <div class="kpi-box">
        <div class="kpi-lbl">Estratègia</div>
        <div class="kpi-val" style="color:{strat_col_c};">{ret_strat:+.2f}%</div>
      </div>
      <div class="kpi-box">
        <div class="kpi-lbl">B&amp;H</div>
        <div class="kpi-val" style="color:{bh_col_c};">{ret_bh:+.2f}%</div>
      </div>
    </div>
    <div class="asset-card-meta">
      <span>Dif: <b style="color:{diff_col};">{diff_sign}{diff:.2f}%</b></span>
      <span>·</span><span>{n_ops} ops</span>
      <span>·</span><span>Encert: <b>{winrate:.0f}%</b></span>
      <span>·</span><span>DD: <b style="color:#dc2626;">{max_dd:.2f}%</b></span>
      <span>·</span><span>Comis.: <b style="color:#b45309;">{fees_asset:,.0f}€</b></span>
    </div>
    <div class="asset-card-chart">{mini_svg}</div>
  </div>
</details>""")

            full_cards_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans',sans-serif;background:transparent;color:#f1f5f9;}}

.cards-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:14px;padding:6px 2px;
}}

.asset-card{{
  background:#111111;
  border:1px solid #2a2a2a;
  border-radius:14px;
  box-shadow:0 1px 3px rgba(0,0,0,.4);
  overflow:hidden;
  transition:box-shadow .18s ease, border-color .18s ease, transform .1s ease;
}}
.asset-card:hover{{
  box-shadow:0 4px 16px rgba(59,130,246,.15), 0 1px 3px rgba(0,0,0,.4);
  border-color:#3a3a3a;
}}
.asset-card[open]{{
  border-color:#3b82f6;
  box-shadow:0 6px 20px rgba(59,130,246,.25), 0 1px 3px rgba(0,0,0,.4);
}}

.asset-card-head{{
  display:flex;align-items:center;gap:12px;
  padding:12px 14px;
  cursor:pointer;
  list-style:none;
  user-select:none;
  transition:background .15s ease;
}}
.asset-card-head::-webkit-details-marker{{display:none;}}
.asset-card-head:hover{{background:#1a1a1a;}}
.asset-card[open] .asset-card-head{{
  background:linear-gradient(90deg,#1a1a1a 0%,rgba(59,130,246,.1) 100%);
  border-bottom:1px solid #2a2a2a;
}}

.asset-card-info{{flex:1;min-width:0;}}
.asset-card-tk{{
  font-family:'DM Mono',monospace;
  font-size:.7rem;color:#60a5fa;font-weight:700;
  letter-spacing:.06em;line-height:1;
}}
.asset-card-name{{
  font-size:.88rem;font-weight:600;color:#f1f5f9;
  line-height:1.25;margin-top:3px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}}

.asset-card-weight{{
  background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.35);
  border-radius:14px;padding:2px 10px;
  font-size:.68rem;color:#93c5fd;font-weight:700;white-space:nowrap;
  font-family:'DM Mono',monospace;
}}

.asset-card-chevron{{
  color:#64748b;font-size:.85rem;
  transition:transform .2s ease;
  margin-left:2px;
}}
.asset-card[open] .asset-card-chevron{{
  transform:rotate(180deg);
  color:#60a5fa;
}}

.asset-card-body{{padding:10px 14px 14px;}}

.asset-card-kpis{{
  display:grid;grid-template-columns:1fr 1fr;gap:6px;
  margin-bottom:6px;
}}
.kpi-box{{
  background:#1a1a1a;border-radius:8px;
  padding:6px 10px;border:1px solid #242424;
}}
.kpi-lbl{{
  font-size:.6rem;color:#94a3b8;font-weight:600;
  text-transform:uppercase;letter-spacing:.04em;
}}
.kpi-val{{
  font-family:'DM Mono',monospace;
  font-size:.9rem;font-weight:700;margin-top:1px;
}}

.asset-card-meta{{
  display:flex;gap:6px;flex-wrap:wrap;align-items:center;
  font-size:.68rem;color:#94a3b8;
  padding:5px 2px 0;
}}
.asset-card-meta b{{font-family:'DM Mono',monospace;}}

.asset-card-chart{{
  margin-top:10px;
  background:#000000;
  border-radius:10px;
  padding:8px 4px 2px;
  overflow:hidden;
  border:1px solid #1a1a1a;
}}
.asset-card-chart svg{{width:100%;height:auto;display:block;}}
</style></head>
<body>
<div class="cards-grid">
{''.join(card_blocks)}
</div>
<script>
// Comuniquem dinàmicament l'alçada real al Streamlit quan les targetes
// s'obren/tanquen perquè l'iframe no deixi espai extra ni scroll.
(function() {{
  function sendHeight() {{
    const h = Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight,
      document.querySelector('.cards-grid')?.offsetHeight || 0
    );
    // Streamlit components API (versió client)
    if (window.Streamlit && window.Streamlit.setFrameHeight) {{
      window.Streamlit.setFrameHeight(h + 16);
    }} else {{
      // Fallback: parla directament amb l'iframe parent
      window.parent.postMessage({{
        type: 'streamlit:setFrameHeight',
        height: h + 16
      }}, '*');
    }}
  }}

  // Observem canvis a qualsevol <details> (obertura/tancament)
  document.querySelectorAll('details.asset-card').forEach(d => {{
    d.addEventListener('toggle', () => {{ setTimeout(sendHeight, 50); }});
  }});

  // També al carregar i redimensionar
  window.addEventListener('load', sendHeight);
  window.addEventListener('resize', sendHeight);
  // Crida inicial després d'un petit retard perquè tot estigui renderitzat
  setTimeout(sendHeight, 100);
  setTimeout(sendHeight, 500);
}})();
</script>
</body></html>"""

            # Alçada inicial generosa: el script s'encarregarà d'ajustar-la
            # a la real quan carregui l'iframe i quan s'obrin/tanquin cards.
            n_cards = len(card_blocks)
            rows_approx = max(1, (n_cards + 2) // 3)
            initial_h = rows_approx * 110 + 40
            components.html(full_cards_html, height=initial_h, scrolling=False)

        # ──────────────────────────────────────────────────────
        # Sub-tab NOVA: Taula completa (comparativa Estratègia/B&H/MSCI)
        # ──────────────────────────────────────────────────────
        with pb_sub_table:
            st.markdown(
                "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:14px;line-height:1.5;'>"
                "Anàlisi comparativa de l'<b>estratègia agregada</b> de la cartera "
                "vs <b>Buy &amp; Hold equal-weight</b> de la mateixa cartera "
                "vs índex de referència <b>MSCI World</b> per al període seleccionat."
                "</div>",
                unsafe_allow_html=True,
            )

            # ─── Calculem mètriques agregades per Estratègia / B&H / MSCI ───
            import math as _math
            def _compute_metrics(values: list[float], dates: list[str]) -> dict:
                """Donada una sèrie de valors (capital), retorna mètriques."""
                if not values or len(values) < 2:
                    return {"ret":0.0,"cagr":0.0,"vol":0.0,"sharpe":0.0,"maxdd":0.0,"days":0}
                v0, vN = values[0], values[-1]
                ret = (vN/v0 - 1.0) * 100.0
                # CAGR
                t0 = pd.to_datetime(dates[0])
                tN = pd.to_datetime(dates[-1])
                yrs = max((tN - t0).days / 365.25, 0.01)
                cagr = ((vN/v0) ** (1/yrs) - 1) * 100.0 if v0 > 0 else 0.0
                # Volatilitat anual
                returns = []
                for i in range(1, len(values)):
                    if values[i-1] > 0:
                        returns.append(values[i]/values[i-1] - 1.0)
                if returns:
                    mean_r = sum(returns)/len(returns)
                    var_r = sum((r-mean_r)**2 for r in returns) / max(len(returns)-1, 1)
                    std_r = _math.sqrt(var_r)
                    vol_ann = std_r * _math.sqrt(252) * 100
                    sharpe = (mean_r * 252) / (std_r * _math.sqrt(252)) if std_r > 0 else 0.0
                else:
                    vol_ann = 0.0
                    sharpe = 0.0
                # Max drawdown
                peak = values[0]
                maxdd = 0.0
                for v in values:
                    peak = max(peak, v)
                    dd = (v - peak) / peak * 100 if peak > 0 else 0.0
                    maxdd = min(maxdd, dd)
                return {
                    "ret": ret, "cagr": cagr, "vol": vol_ann,
                    "sharpe": sharpe, "maxdd": maxdd, "days": (tN - t0).days,
                }

            # Estratègia: pf_equity_points (BRUT)
            strat_dates = [p["time"] for p in pf_equity_points]
            strat_values = [float(p["value"]) for p in pf_equity_points]
            m_strat = _compute_metrics(strat_values, strat_dates)

            # B&H: pf_bh_equity_points (BRUT — NET de comissions, però
            # abans d'IRPF). Mateixos costos que els KPIs del top.
            if pf_bh_equity_points:
                bh_dates_list = [p["time"] for p in pf_bh_equity_points]
                bh_values = [float(p["value"]) for p in pf_bh_equity_points]
                m_bh = _compute_metrics(bh_values, bh_dates_list)
            else:
                m_bh = {"ret":0.0,"cagr":0.0,"vol":0.0,"sharpe":0.0,"maxdd":0.0,"days":0}

            # ── CORBES NETES D'IMPOSTOS (si la fiscalitat és activa) ──
            # Quan tax_cfg.enabled, calculem les mateixes mètriques sobre
            # la corba descomptant l'impost de cada exercici al 31/12. La
            # diferència entre m_strat["ret"] i m_strat_net["ret"] és el
            # "cost fiscal" en punts percentuals.
            if tax_cfg.enabled:
                strat_net_points = apply_tax_to_equity(
                    pf_equity_points, pf_tax_summary.yearly
                )
                strat_net_vals = [float(p["value"]) for p in strat_net_points]
                m_strat_net = _compute_metrics(strat_net_vals, strat_dates)

                if pf_bh_equity_points:
                    bh_net_points = apply_tax_to_equity(
                        pf_bh_equity_points, pf_bh_tax_summary.yearly
                    )
                    bh_net_vals = [float(p["value"]) for p in bh_net_points]
                    m_bh_net = _compute_metrics(bh_net_vals, bh_dates_list)
                else:
                    m_bh_net = m_bh
            else:
                m_strat_net = m_strat
                m_bh_net = m_bh

            # ── MSCI World tractat com a ETF (amb comissió + TER + IRPF) ──
            # En lloc de mostrar l'índex PUR (sense costos), modelem la
            # inversió en un ETF que rèplica el MSCI World. Així la
            # comparació és justa: l'estratègia i el B&H paguen costos,
            # i el benchmark també. Costos modelats:
            #   • Comissió de compra + venda (1 transmissió cada)
            #   • Slippage compra + venda
            #   • TER anual prorratejat per dies (gestió ETF)
            #   • IRPF: una sola venda al final del període → 1 fet imposable
            msci_df_local = load_msci_world(INDICES_PATH)
            m_msci = {"ret":0.0,"cagr":0.0,"vol":0.0,"sharpe":0.0,"maxdd":0.0,"days":0}
            m_msci_net = m_msci
            msci_etf_result = None
            msci_total_fees = 0.0
            msci_total_tax = 0.0
            msci_dates_list: list[str] = []

            if msci_df_local is not None:
                msci_local = msci_df_local[
                    (msci_df_local["Date"].dt.date >= date_from) &
                    (msci_df_local["Date"].dt.date <= date_to)
                ].copy().reset_index(drop=True)
                if not msci_local.empty:
                    # Construïm la corba d'ETF amb tots els costos
                    msci_etf_result = build_msci_etf_equity(
                        msci_local,
                        capital_inicial=float(capital_total),
                        fee_pct=float(fee_pct_pf) / 100.0,
                        slippage_buy_pct=0.0,
                        slippage_sell_pct=0.0,
                        ter_annual_pct=float(msci_ter_pct_pf) / 100.0,
                    )
                    msci_total_fees = msci_etf_result["total_fees"]

                    # Mètriques BRUTES (amb costos d'ETF però sense IRPF)
                    msci_eq_pts = msci_etf_result["equity"]
                    msci_dates_list = [p["time"] for p in msci_eq_pts]
                    msci_values = [float(p["value"]) for p in msci_eq_pts]
                    m_msci = _compute_metrics(msci_values, msci_dates_list)

                    # Mètriques NETES d'IRPF (1 sola venda al final del període
                    # = 1 fet imposable, idèntic al tractament del B&H)
                    if tax_cfg.enabled:
                        msci_pnl = (msci_etf_result["capital_final"]
                                    - msci_etf_result["capital_inicial"])
                        msci_sales = [TaxableSale(
                            ticker="MSCI_WORLD",
                            sell_date=_to_date(str(date_to)),
                            buy_date=_to_date(str(date_from)),
                            pnl=msci_pnl,
                        )]
                        msci_tax_summary = compute_tax_summary(msci_sales, tax_cfg)
                        msci_total_tax = msci_tax_summary.total_tax

                        msci_net_points = apply_tax_to_equity(
                            msci_eq_pts, msci_tax_summary.yearly
                        )
                        msci_net_vals = [float(p["value"]) for p in msci_net_points]
                        m_msci_net = _compute_metrics(msci_net_vals, msci_dates_list)

            # ─── Render: targetes comparatives ───
            def _color_for(value: float, key: str) -> str:
                """Color verd si bo, vermell si dolent, segons el tipus de mètrica."""
                if key in ("ret", "cagr"):
                    return "#16a34a" if value >= 0 else "#dc2626"
                if key == "sharpe":
                    return "#16a34a" if value >= 1 else ("#f59e0b" if value >= 0 else "#dc2626")
                if key == "maxdd":
                    return "#dc2626"
                if key == "vol":
                    return "#94a3b8"
                return "#f1f5f9"

            def _cell(label: str, value: str, color: str) -> str:
                """Construeix una cel·la individual <td> amb etiqueta i valor."""
                return (
                    f"<td style='padding:10px 14px;vertical-align:top;'>"
                    f"<div style='font-size:.62rem;color:#94a3b8;font-weight:700;"
                    f"text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;"
                    f"white-space:nowrap;'>{label}</div>"
                    f"<div style='font-family:\"DM Mono\",monospace;font-size:1rem;"
                    f"font-weight:700;color:{color};white-space:nowrap;'>{value}</div>"
                    f"</td>"
                )

            def _empty_cell() -> str:
                """Cel·la buida amb un guió neutre (per MSCI a columnes que no apliquen)."""
                return (
                    "<td style='padding:10px 14px;vertical-align:top;'>"
                    "<div style='font-family:\"DM Mono\",monospace;font-size:1rem;"
                    "font-weight:700;color:#475569;'>—</div></td>"
                )

            def _row(
                name: str,
                color_accent: str,
                m_brut: dict,
                m_net: dict | None = None,
                fees: float | None = None,
                taxes: float | None = None,
            ) -> str:
                """Construeix una fila de la taula comparativa.

                Si la fiscalitat NO és activa o `m_net` és None, la columna
                "Retorn net" es mostra com "—". Si `fees` o `taxes` són
                None (cas MSCI), aquelles columnes també es mostren buides.
                """
                show_tax = tax_cfg.enabled
                ret_brut = m_brut['ret']
                cells = []
                # Retorn brut — sempre present
                cells.append(_cell(
                    "Retorn brut", f"{ret_brut:+.2f}%",
                    _color_for(ret_brut, 'ret'),
                ))
                # Retorn net — només si hi ha m_net i fiscalitat activa
                if show_tax and m_net is not None:
                    ret_net = m_net['ret']
                    cells.append(_cell(
                        "Retorn net", f"{ret_net:+.2f}%",
                        _color_for(ret_net, 'ret'),
                    ))
                else:
                    cells.append(_cell(
                        "Retorn net",
                        "—" if not show_tax else f"{ret_brut:+.2f}%",
                        "#475569" if not show_tax else _color_for(ret_brut, 'ret'),
                    ))
                # Comissions — només per Estratègia/B&H
                if fees is not None:
                    cells.append(_cell(
                        "Comissions", f"{fees:,.0f}€", "#f59e0b",
                    ))
                else:
                    cells.append(_empty_cell())
                # Impostos — només si fiscalitat activa i no MSCI
                if show_tax and taxes is not None:
                    cells.append(_cell(
                        "Impostos IRPF", f"{taxes:,.0f}€", "#fbbf24",
                    ))
                elif taxes is not None:
                    cells.append(_cell(
                        "Impostos IRPF", "—", "#475569",
                    ))
                else:
                    cells.append(_empty_cell())
                # CAGR / Volatilitat / Sharpe / MaxDD — sempre
                cells.append(_cell(
                    "CAGR", f"{m_brut['cagr']:+.2f}%",
                    _color_for(m_brut['cagr'], 'cagr'),
                ))
                cells.append(_cell(
                    "Volatilitat", f"{m_brut['vol']:.2f}%",
                    _color_for(m_brut['vol'], 'vol'),
                ))
                cells.append(_cell(
                    "Sharpe", f"{m_brut['sharpe']:.2f}",
                    _color_for(m_brut['sharpe'], 'sharpe'),
                ))
                cells.append(_cell(
                    "Màx. Drawdown", f"{m_brut['maxdd']:.2f}%",
                    _color_for(m_brut['maxdd'], 'maxdd'),
                ))
                return (
                    f"<tr style='background:#111111;'>"
                    f"<td style='padding:10px 14px 10px 16px;"
                    f"border-left:3px solid {color_accent};vertical-align:top;'>"
                    f"<div style='font-size:.85rem;font-weight:700;color:#f1f5f9;'>"
                    f"{name}</div></td>"
                    + "".join(cells)
                    + f"</tr>"
                )

            # Comissions del B&H: 1 compra + 1 venda per actiu. Es deriva
            # de res["bh_buy_fee"] + res["bh_sell_fee"] (calculats al motor).
            bh_total_fees = sum(
                float(d["result"].get("bh_buy_fee", 0.0))
                + float(d["result"].get("bh_sell_fee", 0.0))
                for d in per_asset_data.values()
            )

            comp_html = (
                "<div style='border:1px solid #2a2a2a;border-radius:12px;overflow:auto;"
                "box-shadow:0 2px 10px rgba(0,0,0,.4);margin-bottom:18px;'>"
                "<table style='width:100%;border-collapse:separate;border-spacing:0 1px;"
                "background:#0a0a0a;'>"
                + _row("📈 Estratègia", "#10b981", m_strat, m_strat_net,
                       fees=total_fees_pf, taxes=pf_total_tax)
                + _row("📊 Buy &amp; Hold (cartera)", "#3b82f6", m_bh, m_bh_net,
                       fees=bh_total_fees, taxes=pf_bh_total_tax)
                + _row("🌍 MSCI World", "#f59e0b", m_msci, m_msci_net,
                       fees=msci_total_fees, taxes=msci_total_tax)
                + "</table></div>"
            )
            st.markdown(comp_html, unsafe_allow_html=True)

            # Llegenda d'ajuda i estat de la fiscalitat
            tax_status_html = (
                "<span style='color:#10b981;'>✓ activa</span>"
                if tax_cfg.enabled else
                "<span style='color:#94a3b8;'>⚪ desactivada</span>"
            )
            mode_label = (
                "escala vigent de cada exercici"
                if tax_cfg.per_year_scale else "escala fixa"
            )
            st.markdown(
                f"<div style='font-size:.78rem;color:#94a3b8;margin-top:6px;"
                f"line-height:1.55;'>"
                f"💡 La columna <b>Retorn net</b> és el rendiment després "
                f"d'aplicar comissions i IRPF. Fiscalitat: {tax_status_html}"
                + (f" ({mode_label})" if tax_cfg.enabled else "")
                + ". El càlcul d'impostos del <b>B&amp;H</b> correspon a "
                "una única transmissió al final del període; el de "
                "l'<b>Estratègia</b>, a la liquidació anual de les "
                "operacions tancades cada exercici. Per canviar el mode o "
                "desactivar la fiscalitat, ves a la pestanya "
                "<b>Fiscalitat</b>."
                "</div>",
                unsafe_allow_html=True,
            )

            # ─── Taula visual interactiva amb els 30 actius ───
            st.markdown(
                "<div style='font-size:.72rem;color:#94a3b8;font-weight:700;"
                "text-transform:uppercase;letter-spacing:.06em;margin:8px 0 8px 0;'>"
                "📋 Detall per actiu</div>",
                unsafe_allow_html=True,
            )

            # Construïm una taula visual amb logos + barres de retorn
            ranked = df_res.sort_values("Pes (%)", ascending=False).reset_index(drop=True)
            max_abs_ret = max(
                abs(ranked["Retorn estratègia (%)"].max() or 0),
                abs(ranked["Retorn estratègia (%)"].min() or 0),
                1.0,
            )

            rows_html = []
            # tax_show: si True, mostrem les columnes "Net" i "Impostos".
            # Si la fiscalitat està desactivada, no apareixen perquè no
            # aporten informació.
            tax_show = tax_cfg.enabled

            for _, r in ranked.iterrows():
                tk = r["Ticker"]
                cn = r["Companyia"]
                pes = float(r["Pes (%)"])
                ret_strat = float(r["Retorn estratègia (%)"])
                ret_bh = float(r["Retorn B&H (%)"])
                n_ops = int(r["Operacions"])
                max_dd_a = float(r["Max DD (%)"])
                winrate = float(r["Taxa encert (%)"])
                fees_a = float(r["Comissions (€)"]) if "Comissions (€)" in r else 0.0
                tax_a = float(r["Impostos IRPF (€)"]) if "Impostos IRPF (€)" in r else 0.0
                ret_strat_net = (
                    float(r["Retorn estratègia net (%)"])
                    if "Retorn estratègia net (%)" in r else ret_strat
                )
                ret_bh_net = (
                    float(r["Retorn B&H net (%)"])
                    if "Retorn B&H net (%)" in r else ret_bh
                )

                strat_col = "#10b981" if ret_strat >= 0 else "#ef4444"
                strat_net_col = "#10b981" if ret_strat_net >= 0 else "#ef4444"
                bh_col = "#3b82f6" if ret_bh >= 0 else "#2563eb"
                bh_net_col = "#3b82f6" if ret_bh_net >= 0 else "#2563eb"
                diff = ret_strat - ret_bh
                diff_col = "#10b981" if diff >= 0 else "#ef4444"

                # Barra de retorn estratègia (sempre sobre el brut)
                bar_w = min(50.0, abs(ret_strat) / max_abs_ret * 50.0)

                # Logo
                logo_snippet = _logo_html(tk, cn, size=28)

                # Files NET i IMPOSTOS només si fiscalitat activa
                net_strat_cell = (
                    f"<td style='padding:8px 10px;text-align:right;"
                    f"font-family:\"DM Mono\",monospace;font-size:.78rem;"
                    f"color:{strat_net_col};font-weight:600;'>{ret_strat_net:+.2f}%</td>"
                ) if tax_show else ""
                net_bh_cell = (
                    f"<td style='padding:8px 10px;text-align:right;"
                    f"font-family:\"DM Mono\",monospace;font-size:.78rem;"
                    f"color:{bh_net_col};font-weight:600;'>{ret_bh_net:+.2f}%</td>"
                ) if tax_show else ""
                tax_cell = (
                    f"<td style='padding:8px 10px;text-align:right;"
                    f"font-family:\"DM Mono\",monospace;font-size:.78rem;"
                    f"color:#fbbf24;font-weight:600;'>{tax_a:,.0f}€</td>"
                ) if tax_show else ""

                rows_html.append(
                    f"<tr style='background:#111111;'>"
                    f"<td style='padding:8px 10px;'>{logo_snippet}</td>"
                    f"<td style='padding:8px 10px;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:#60a5fa;font-weight:700;letter-spacing:.04em;'>{tk}</td>"
                    f"<td style='padding:8px 10px;font-size:.85rem;color:#f1f5f9;font-weight:500;'>{cn}</td>"
                    f"<td style='padding:8px 10px;text-align:right;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:#cbd5e1;'>{pes:.2f}%</td>"
                    # Retorn estratègia BRUT amb barra
                    f"<td style='padding:8px 10px;position:relative;min-width:160px;'>"
                    f"  <div style='position:relative;height:18px;background:#0a0a0a;border-radius:3px;'>"
                    f"    <div style='position:absolute;top:0;{'left:50%;' if ret_strat >= 0 else 'right:50%;'}"
                    f"      width:{bar_w}%;height:18px;background:{strat_col};opacity:.35;border-radius:3px;'></div>"
                    f"    <div style='position:absolute;top:0;left:50%;width:1px;height:18px;background:#2a2a2a;'></div>"
                    f"    <div style='position:absolute;top:0;left:0;right:0;height:18px;display:flex;"
                    f"      align-items:center;justify-content:center;font-family:\"DM Mono\",monospace;"
                    f"      font-size:.74rem;font-weight:700;color:{strat_col};'>{ret_strat:+.2f}%</div>"
                    f"  </div>"
                    f"</td>"
                    # NOU: Retorn estratègia NET (si fiscalitat activa)
                    + net_strat_cell
                    # Retorn B&H BRUT
                    + f"<td style='padding:8px 10px;text-align:right;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:{bh_col};font-weight:600;'>{ret_bh:+.2f}%</td>"
                    # NOU: Retorn B&H NET (si fiscalitat activa)
                    + net_bh_cell
                    # Diferència (sobre el BRUT, perquè és la mesura
                    # d'alpha original; si vols la diferència NET, la
                    # tens al càlcul d'avantatge de la taula comparativa)
                    + f"<td style='padding:8px 10px;text-align:right;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:{diff_col};font-weight:700;'>{diff:+.2f}%</td>"
                    + f"<td style='padding:8px 10px;text-align:right;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:#cbd5e1;'>{n_ops}</td>"
                    + f"<td style='padding:8px 10px;text-align:right;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:#f59e0b;font-weight:600;'>{fees_a:,.0f}€</td>"
                    # NOU: Impostos IRPF (si fiscalitat activa)
                    + tax_cell
                    + f"<td style='padding:8px 10px;text-align:right;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:#cbd5e1;'>{winrate:.0f}%</td>"
                    + f"<td style='padding:8px 10px;text-align:right;font-family:\"DM Mono\",monospace;"
                    f"font-size:.78rem;color:#dc2626;font-weight:600;'>{max_dd_a:.2f}%</td>"
                    + f"</tr>"
                )

            # Capçaleres dinàmiques: si fiscalitat activa, hi ha 2 columnes
            # extres (Net Estratègia i Net B&H) i 1 més (Impostos IRPF).
            headers = [
                ("", "left"),
                ("Ticker", "left"),
                ("Companyia", "left"),
                ("Pes", "right"),
                ("Retorn Estratègia (brut)" if tax_show else "Retorn Estratègia", "center"),
            ]
            if tax_show:
                headers.append(("Net (post IRPF)", "right"))
            headers.append(("Retorn B&H (brut)" if tax_show else "Retorn B&H", "right"))
            if tax_show:
                headers.append(("B&H net", "right"))
            headers.extend([
                ("Diferència", "right"),
                ("Ops", "right"),
                ("Comissions", "right"),
            ])
            if tax_show:
                headers.append(("Impostos IRPF", "right"))
            headers.extend([
                ("Encert", "right"),
                ("Max DD", "right"),
            ])

            # Fila de TOTALS: comissions i (si escau) impostos acumulats.
            # El colspan inicial varia segons quantes columnes hi ha
            # abans de "Ops". Comptem-les: les 4 fixes (logo, ticker,
            # companyia, pes) + Retorn Estratègia (+ Net si tax) +
            # Retorn B&H (+ Net si tax) + Diferència = 7 o 9.
            cols_before_ops = 7 + (2 if tax_show else 0)
            tot_tax_pf = float(df_res["Impostos IRPF (€)"].sum()) if tax_show else 0.0
            tax_total_cell = (
                f"<td style='padding:10px;text-align:right;font-family:\"DM Mono\",monospace;"
                f"font-size:.78rem;color:#fbbf24;font-weight:700;'>{tot_tax_pf:,.0f}€</td>"
            ) if tax_show else ""
            totals_row_html = (
                "<tr style='background:#1e293b;'>"
                f"<td colspan='{cols_before_ops}' style='padding:10px;text-align:right;"
                f"color:#e2e8f0;font-weight:700;font-size:.7rem;text-transform:uppercase;"
                f"letter-spacing:.05em;'>Totals de la cartera</td>"
                f"<td style='padding:10px;text-align:right;font-family:\"DM Mono\",monospace;"
                f"font-size:.78rem;color:#e2e8f0;font-weight:700;'>{total_trades}</td>"
                f"<td style='padding:10px;text-align:right;font-family:\"DM Mono\",monospace;"
                f"font-size:.78rem;color:#fbbf24;font-weight:700;'>{total_fees_pf:,.0f}€</td>"
                + tax_total_cell
                + "<td colspan='2'></td>"
                + "</tr>"
            )

            visual_table = (
                "<div style='border:1px solid #2a2a2a;border-radius:12px;overflow:auto;"
                "max-height:600px;box-shadow:0 2px 10px rgba(0,0,0,.4);'>"
                "<table style='width:100%;border-collapse:separate;border-spacing:0 1px;"
                "background:#0a0a0a;font-family:\"DM Sans\",sans-serif;'>"
                "<thead style='position:sticky;top:0;z-index:1;'>"
                "<tr style='background:#0a0a0a;'>"
                + "".join(
                    f"<th style='padding:10px 10px;font-size:.65rem;color:#94a3b8;"
                    f"font-weight:700;text-transform:uppercase;letter-spacing:.06em;"
                    f"text-align:{ta};border-bottom:1px solid #2a2a2a;'>{h}</th>"
                    for h, ta in headers
                )
                + "</tr></thead><tbody>"
                + "".join(rows_html)
                + "</tbody>"
                + f"<tfoot style='position:sticky;bottom:0;z-index:1;'>{totals_row_html}</tfoot>"
                + "</table></div>"
            )
            st.markdown(visual_table, unsafe_allow_html=True)

            # ── Nota important: per què la suma per actiu NO és el total real ──
            # Quan la fiscalitat és activa, l'usuari pot comparar la suma
            # d'"Impostos IRPF" del peu d'aquesta taula (orientatiu per
            # actiu) amb el total de la fila Estratègia de la taula
            # comparativa de dalt (correcte, càlcul global). Sempre seran
            # diferents per culpa de la progressivitat de l'escala — cal
            # explicar-ho explícitament per evitar la pregunta natural
            # "per què no quadren?".
            if tax_cfg.enabled:
                tot_tax_per_asset = float(df_res["Impostos IRPF (€)"].sum())
                diff_pa = pf_total_tax - tot_tax_per_asset
                st.markdown(
                    f"<div style='background:#1a1410;border-left:3px solid #fbbf24;"
                    f"padding:11px 14px;border-radius:6px;margin-top:10px;"
                    f"font-size:.78rem;color:#cbd5e1;line-height:1.55;'>"
                    f"<b style='color:#fbbf24;'>⚠️ Nota sobre la columna "
                    f"Impostos IRPF d'aquesta taula:</b><br>"
                    f"La quota mostrada per cada actiu és <b>orientativa</b> — "
                    f"es calcula com si cada acció fos l'única inversió del "
                    f"contribuent. La suma del peu ("
                    f"<span style='color:#fbbf24;font-weight:700;'>"
                    f"{tot_tax_per_asset:,.0f}€</span>) <b>no coincideix</b> "
                    f"amb l'impost real de la cartera ("
                    f"<span style='color:#fbbf24;font-weight:700;'>"
                    f"{pf_total_tax:,.0f}€</span>, diferència de "
                    f"<b>{abs(diff_pa):,.0f}€</b>) per dues raons:<br>"
                    f"&nbsp;&nbsp;<b>1.</b> L'escala de l'estalvi és "
                    f"<b>progressiva per trams</b>. La base de la cartera "
                    f"sencera salta a trams superiors (21 %, 23 %...) que "
                    f"els actius individuals, més petits, no toquen.<br>"
                    f"&nbsp;&nbsp;<b>2.</b> Les pèrdues d'un actiu poden "
                    f"<b>compensar</b> guanys d'un altre dins el mateix "
                    f"exercici, cosa que en el càlcul per actiu no passa.<br>"
                    f"L'<b>impost fiscalment vàlid</b> és el de la <b>taula "
                    f"comparativa</b> de dalt ("
                    f"<span style='color:#fbbf24;font-weight:700;'>"
                    f"{pf_total_tax:,.0f}€</span>) i el de la pestanya "
                    f"<b>Fiscalitat</b>, perquè la base de l'estalvi "
                    f"a l'IRPF és <b>global del contribuent</b>, no per valor."
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # CSV descarregable
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.download_button(
                label="📥 Descarregar taula completa (CSV)",
                data=_df_to_csv_bytes(df_res),
                file_name=f"taula_completa_{date_from}_{date_to}.csv",
                mime="text/csv",
                key="dl_taula_completa",
            )

        # ── Sub-tab 1: Reproductor per actiu seleccionable ──
        with pb_sub1:
            st.markdown(
                "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:10px;line-height:1.5;'>"
                "Tria un actiu per reproduir-ne el backtest dia a dia. "
                "Passa el ratolí sobre les fletxes 🟢🔴 per veure els criteris complerts."
                "</div>",
                unsafe_allow_html=True,
            )
            pb_options = [f"{tk}  —  {d['company']}" for tk, d in per_asset_data.items()]
            chosen_pb = st.selectbox(
                "Actiu per reproduir:",
                options=pb_options,
                key="pb_cartera_sel",
            )
            chosen_tk = chosen_pb.split("  —  ")[0].strip()
            asset_info = per_asset_data.get(chosen_tk)
            if asset_info:
                # Logo badge de l'actiu seleccionat
                st.markdown(
                    f"""<div style="display:flex;align-items:center;gap:12px;
                                    background:linear-gradient(100deg,#0f172a 0%,#1e3a5f 100%);
                                    border:1px solid #1e293b;border-radius:10px;
                                    padding:10px 14px;margin:8px 0 12px 0;">
                      {_logo_html(chosen_tk, asset_info['company'], size=36)}
                      <div style="flex:1;min-width:0;">
                        <div style="font-family:'DM Mono',monospace;font-size:.68rem;color:#60a5fa;
                                     font-weight:700;letter-spacing:.08em;">{chosen_tk}</div>
                        <div style="font-size:.95rem;color:#f1f5f9;font-weight:600;line-height:1.2;margin-top:1px;">
                          {asset_info['company']}
                        </div>
                      </div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                pb_html = _build_replay_chart_html(
                    asset_info["dataset"],
                    chosen_tk,
                    asset_info["company"],
                    asset_info["result"],
                )
                components.html(pb_html, height=1100, scrolling=False)

        # ── Sub-tab 2: Línia temporal agregada ──
        with pb_sub2:
            st.markdown(
                "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:10px;line-height:1.5;'>"
                "Totes les operacions de tots els actius de la cartera, ordenades cronològicament. "
                "Útil per veure clústers d'activitat (dies amb múltiples compres alhora)."
                "</div>",
                unsafe_allow_html=True,
            )

            # Recollim tots els esdeveniments i els ordenem per data
            all_events = []
            for tk, d in per_asset_data.items():
                logo_uri_tk = _load_logo_b64(tk, d["company"])
                for s in d["result"]["signals"]:
                    ev = {
                        "time": str(s["time"]).replace(" *", ""),
                        "ticker": tk,
                        "company": d["company"],
                        "logo_uri": logo_uri_tk,       # pot ser None si no es troba
                        "type": s["type"],
                        "price": s.get("price") or s.get("close"),
                    }
                    if s["type"] == "buy":
                        ev["shares"] = s.get("shares", 0)
                        ev["invested"] = s.get("invested", 0)
                    else:
                        ev["pnl"] = s.get("pnl", 0)
                        ev["ret_pct"] = s.get("ret_pct", 0)
                        ev["days"] = s.get("days", 0)
                    all_events.append(ev)

            all_events.sort(key=lambda e: (e["time"], e["ticker"]))

            timeline_html = _build_portfolio_timeline_html(
                all_events, str(date_from), str(date_to), len(per_asset_data)
            )
            components.html(timeline_html, height=780, scrolling=False)

            # CSV descarregable del timeline (sense la columna logo_uri,
            # que seria enorme perquè són data-URIs base64)
            if all_events:
                df_timeline = pd.DataFrame(all_events).drop(columns=["logo_uri"], errors="ignore")
                csv_tl = _df_to_csv_bytes(df_timeline)
                st.download_button(
                    label="📥 Descarregar línia temporal (CSV)",
                    data=csv_tl,
                    file_name=f"timeline_cartera_{date_from}_{date_to}.csv",
                    mime="text/csv",
                    key="dl_timeline",
                )

        # ── Sub-tab 3: Corba de capital agregada vs MSCI World ──
        with pb_sub3:
            st.markdown(
                "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:10px;line-height:1.5;'>"
                "Evolució del capital de la cartera sencera: suma de tots els equities "
                "individuals agregada al temps. Comparada amb un <b>Buy &amp; Hold equal-weight</b> "
                "de la mateixa cartera i amb l'índex <b>MSCI World</b>."
                "</div>",
                unsafe_allow_html=True,
            )

            # ── Carreguem MSCI World ─────────────────
            msci_df_pf = load_msci_world(INDICES_PATH)
            if msci_df_pf is None:
                st.markdown(
                    f"<div style='padding:8px 14px;background:#fef3c7;border:1px solid #fcd34d;"
                    f"border-radius:8px;font-size:.8rem;color:#92400e;margin-bottom:10px;'>"
                    f"⚠️ No s'ha trobat <code>{MSCI_WORLD_FILENAME}</code> a <code>{INDICES_PATH}</code>. "
                    f"Es mostraran només les corbes Estratègia i B&amp;H."
                    f"</div>",
                    unsafe_allow_html=True,
                )
            msci_period_pf = None
            if msci_df_pf is not None:
                msci_period_pf = msci_df_pf[
                    (msci_df_pf["Date"].dt.date >= date_from) & (msci_df_pf["Date"].dt.date <= date_to)
                ].copy()
                if msci_period_pf.empty:
                    msci_period_pf = None

            # ── Construïm el gràfic ───────────────────
            # La línia B&H del gràfic també ha de ser NET (no l'índex sintètic
            # de preus brut). Convertim `pf_bh_equity_points` (Date+value) al
            # format Date+Close que espera `_build_equity_curve_html`; aquest
            # normalitza internament al primer punt (= capital_total) i mostra
            # la línia amb la base 100 idèntica a l'estratègia.
            #
            # FISCALITAT: si està activa, apliquem l'impost a les dues corbes
            # via apply_tax_to_equity. La corba resultant cau en "graons"
            # cada 31/12 en què s'ha tributat. L'estratègia descompta la seva
            # liquidació anual; el B&H, que difereix, només descompta al final.
            #
            # MSCI WORLD: també es processa com a ETF amb costos (comissions,
            # TER) i, si la fiscalitat és activa, amb IRPF a la venda final.
            # Així les TRES línies del gràfic són directament comparables
            # entre si, totes amb els mateixos tipus de costos.
            curve_equity_pf = pf_equity_points
            curve_bh_points = pf_bh_equity_points
            if tax_cfg.enabled:
                curve_equity_pf = apply_tax_to_equity(
                    pf_equity_points, pf_tax_summary.yearly
                )
                curve_bh_points = apply_tax_to_equity(
                    pf_bh_equity_points, pf_bh_tax_summary.yearly
                )

            bh_curve_df = pd.DataFrame([
                {"Date": p["time"], "Close": p["value"]}
                for p in curve_bh_points
            ]) if curve_bh_points else pd.DataFrame(columns=["Date", "Close"])

            # MSCI per al gràfic: la corba d'ETF (que ja inclou comissions
            # + TER); si la fiscalitat és activa, l'apliquem també (cau un
            # sol "graó" al final perquè és una venda única). El builder
            # espera un DataFrame amb Date+Close: la normalització al primer
            # punt es fa internament, així que passar-li capital € és
            # equivalent a passar-li preus.
            msci_curve_df = None
            if msci_etf_result is not None and msci_etf_result["equity"]:
                msci_equity_pts = msci_etf_result["equity"]
                if tax_cfg.enabled:
                    msci_pnl = (msci_etf_result["capital_final"]
                                - msci_etf_result["capital_inicial"])
                    msci_sales_curve = [TaxableSale(
                        ticker="MSCI_WORLD",
                        sell_date=_to_date(str(date_to)),
                        buy_date=_to_date(str(date_from)),
                        pnl=msci_pnl,
                    )]
                    msci_tax_curve = compute_tax_summary(msci_sales_curve, tax_cfg)
                    msci_equity_pts = apply_tax_to_equity(
                        msci_equity_pts, msci_tax_curve.yearly
                    )
                msci_curve_df = pd.DataFrame([
                    {"Date": p["time"], "Close": p["value"]}
                    for p in msci_equity_pts
                ])
                # IMPORTANT: _resample_index_to_dates (cridada des de
                # _build_equity_curve_html) usa l'accessor .dt sobre la
                # columna Date, que requereix tipus datetime. Si la deixem
                # com a strings (que és el format de "time" als equity
                # points), peta amb "Can only use .dt accessor with
                # datetimelike values". Convertim explícitament aquí.
                msci_curve_df["Date"] = pd.to_datetime(msci_curve_df["Date"])

            curve_subtitle = (
                f"{date_from} → {date_to} · {n_invested} actius invertits"
                + (" · net d'IRPF" if tax_cfg.enabled else "")
            )

            # ── EXPORT CSV PER AL TFG (BRUT + NET) ────────────────────────────
            # Genera un CSV amb SIS corbes: les tres estratègies en versió
            # BRUTA (pre-IRPF, mètriques de rendiment "pures") i en versió
            # NETA (post-IRPF, mètriques de rendiment "reals" per a l'inversor).
            # Permet generar dues versions de les figures (per al 5.3.1 i 5.4
            # del TFG) i una taula comparativa de l'impacte fiscal sobre les
            # mètriques de risc i rendibilitat.
            import os as _os_export
            import sys as _sys_export
            print("=" * 70, file=_sys_export.stderr, flush=True)
            print("[TFG EXPORT] Iniciant exportació equity_curves.csv (brut+net)",
                  file=_sys_export.stderr, flush=True)
            try:
                import pandas as _pd_export

                # ─── CORBES BRUTES (pre-IRPF) ───────────────────────────
                _df_bot_brut = _pd_export.DataFrame([
                    {"date": p["time"], "bot_brut": float(p["value"])}
                    for p in pf_equity_points
                ])
                _df_bh_brut = _pd_export.DataFrame([
                    {"date": p["time"], "buy_hold_brut": float(p["value"])}
                    for p in pf_bh_equity_points
                ])
                _df_export = _df_bot_brut.merge(_df_bh_brut, on="date", how="outer")
                if msci_etf_result is not None and msci_etf_result["equity"]:
                    _df_msci_brut = _pd_export.DataFrame([
                        {"date": p["time"], "msci_world_brut": float(p["value"])}
                        for p in msci_etf_result["equity"]
                    ])
                    _df_export = _df_export.merge(_df_msci_brut, on="date", how="outer")

                # ─── CORBES NETES (post-IRPF, només si fiscalitat activa) ───
                if tax_cfg.enabled:
                    _df_bot_net = _pd_export.DataFrame([
                        {"date": p["time"], "bot_net": float(p["value"])}
                        for p in curve_equity_pf
                    ])
                    _df_bh_net = _pd_export.DataFrame([
                        {"date": p["time"], "buy_hold_net": float(p["value"])}
                        for p in curve_bh_points
                    ])
                    _df_export = _df_export.merge(_df_bot_net, on="date", how="outer")
                    _df_export = _df_export.merge(_df_bh_net, on="date", how="outer")
                    if msci_etf_result is not None and msci_equity_pts:
                        _df_msci_net = _pd_export.DataFrame([
                            {"date": p["time"], "msci_world_net": float(p["value"])}
                            for p in msci_equity_pts
                        ])
                        _df_export = _df_export.merge(_df_msci_net, on="date", how="outer")

                # Ordenar i netejar
                _df_export["date"] = _pd_export.to_datetime(_df_export["date"])
                _df_export = _df_export.sort_values("date").reset_index(drop=True)
                for _col in _df_export.columns:
                    if _col != "date":
                        _df_export[_col] = _df_export[_col].ffill()

                _abs_path = _os_export.path.abspath("equity_curves.csv")
                _df_export.to_csv(_abs_path, index=False)

                # Resum per consola
                print(f"[TFG EXPORT] Columnes exportades: {_df_export.columns.tolist()}",
                      file=_sys_export.stderr, flush=True)
                print(f"[TFG EXPORT] Total files: {len(_df_export)}",
                      file=_sys_export.stderr, flush=True)
                for _col in _df_export.columns:
                    if _col != "date":
                        _vf = _df_export[_col].iloc[-1]
                        _vi = _df_export[_col].iloc[0]
                        _ret = (_vf / _vi - 1) * 100
                        print(f"[TFG EXPORT]   {_col:<20} valor final = {_vf:>14,.2f}  ({_ret:+.2f}%)",
                              file=_sys_export.stderr, flush=True)
                print(f"[TFG EXPORT] ✅ ARXIU CREAT: {_abs_path}",
                      file=_sys_export.stderr, flush=True)
                print("=" * 70, file=_sys_export.stderr, flush=True)

                _ncols_net = sum(1 for c in _df_export.columns if c.endswith("_net"))
                st.success(
                    f"📊 **equity_curves.csv** exportat correctament  \n"
                    f"📁 Ruta: `{_abs_path}`  \n"
                    f"📈 {len(_df_export)} files · "
                    f"{len(_df_export.columns)-1} corbes "
                    f"({'3 brutes + 3 netes' if _ncols_net == 3 else '3 brutes (fiscalitat desactivada)'})",
                    icon="✅"
                )
            except Exception as _e_export:
                import traceback as _tb_export
                _err_msg = _tb_export.format_exc()
                print(f"[TFG EXPORT] ❌ ERROR: {_err_msg}",
                      file=_sys_export.stderr, flush=True)
                st.error(f"❌ Error exportant equity_curves.csv:\n```\n{_err_msg}\n```")
            # ── FI EXPORT CSV ─────────────────────────────────────────────────

            equity_html_pf = _build_equity_curve_html(
                equity_points=curve_equity_pf,
                prices_df=bh_curve_df,
                msci_df=msci_curve_df,
                capital_inicial=float(capital_total),
                title="Corba de capital — Cartera completa",
                subtitle=curve_subtitle,
            )
            components.html(equity_html_pf, height=720, scrolling=False)

            # ── Panell desplegable: liquidacions fiscals detallades ────
            # Útil per al treball: mostra el detall de tots els pagaments
            # d'IRPF que componen la diferència entre la corba bruta i la
            # neta. Per a l'Estratègia, és la liquidació anual completa
            # (un pagament cada 31/12). Per al Buy & Hold, és la
            # transmissió única al final del període.
            if tax_cfg.enabled and (pf_tax_summary.yearly or pf_bh_total_tax > 0):
                with st.expander(
                    f"📋 Liquidacions d'IRPF aplicades a la corba "
                    f"({pf_total_tax:,.2f}€ estratègia · "
                    f"{pf_bh_total_tax:,.2f}€ B&H · "
                    f"{len(pf_tax_summary.yearly)} exercicis)",
                    expanded=False,
                ):
                    st.markdown(
                        "<div style='font-size:.78rem;color:#cbd5e1;margin-bottom:8px;'>"
                        "Cada pagament d'IRPF de l'Estratègia es resta de la "
                        "corba el <b>31 de desembre</b> de l'exercici "
                        "corresponent (això genera els <b>'graons' visibles</b> "
                        "al gràfic). El Buy &amp; Hold només té una "
                        "liquidació, al final del període, perquè difereix "
                        "tota la tributació a la transmissió final.</div>",
                        unsafe_allow_html=True,
                    )

                    # ── Liquidacions anuals de l'ESTRATÈGIA ──
                    st.markdown(
                        "<div style='font-size:.74rem;color:#10b981;font-weight:700;"
                        "text-transform:uppercase;letter-spacing:.06em;"
                        "margin:10px 0 6px;'>"
                        "📈 Estratègia · liquidació exercici per exercici</div>",
                        unsafe_allow_html=True,
                    )
                    if pf_tax_summary.yearly:
                        st.markdown(
                            render_yearly_tax_table(pf_tax_summary.yearly),
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption("(Sense exercicis amb tributació.)")

                    # ── Liquidació única del B&H ──
                    st.markdown(
                        "<div style='font-size:.74rem;color:#3b82f6;font-weight:700;"
                        "text-transform:uppercase;letter-spacing:.06em;"
                        "margin:14px 0 6px;'>"
                        "📊 Buy &amp; Hold · liquidació única al tancament</div>",
                        unsafe_allow_html=True,
                    )
                    if pf_bh_tax_summary.yearly:
                        st.markdown(
                            render_yearly_tax_table(pf_bh_tax_summary.yearly),
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption("(Sense plusvàlua imposable al B&H.)")

                    # Comparativa final del cost fiscal
                    delta_tax = pf_total_tax - pf_bh_total_tax
                    delta_col = "#dc2626" if delta_tax > 0 else "#16a34a"
                    st.markdown(
                        f"<div style='background:#0f172a;border-left:3px solid #fbbf24;"
                        f"padding:10px 14px;border-radius:6px;margin-top:14px;"
                        f"font-size:.82rem;color:#cbd5e1;'>"
                        f"<b>Cost fiscal acumulat:</b> "
                        f"Estratègia <span style='color:#fbbf24;font-weight:700;'>"
                        f"{pf_total_tax:,.2f}€</span> vs B&amp;H "
                        f"<span style='color:#fbbf24;font-weight:700;'>"
                        f"{pf_bh_total_tax:,.2f}€</span> · "
                        f"L'estratègia paga <span style='color:{delta_col};"
                        f"font-weight:700;'>{abs(delta_tax):,.2f}€ "
                        f"{'més' if delta_tax > 0 else 'menys'}</span> en "
                        f"impostos al llarg del període. Aquesta diferència "
                        f"il·lustra l'efecte del <b>diferiment fiscal</b>: "
                        f"el B&amp;H reté el capital tributari dins la "
                        f"inversió durant tot el període, capitalitzant-lo, "
                        f"i només liquida al final."
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            # CSV descarregable de la corba
            if curve_equity_pf:
                df_equity_dl = pd.DataFrame(curve_equity_pf)
                df_equity_dl["Base 100"] = (df_equity_dl["value"] / float(capital_total) * 100.0).round(3)
                df_equity_dl = df_equity_dl.rename(columns={"time": "Data", "value": "Capital (€)"})
                csv_eq = _df_to_csv_bytes(df_equity_dl)
                st.download_button(
                    label="📥 Descarregar corba de capital (CSV)",
                    data=csv_eq,
                    file_name=f"corba_capital_cartera_{date_from}_{date_to}.csv",
                    mime="text/csv",
                    key="dl_equity_pf",
                )


# ─────────────────────────────────────────────────────────────
# MAIN
