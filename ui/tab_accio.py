"""
Pestanya 'Acció Individual':
  • Selector d'empresa amb logo
  • Selector de període (Des de / Fins a / Capital) com a targetes
  • KPIs B&H (5 mètriques)
  • Controls inline (Execució + Costos)
  • 4 sub-pestanyes: Gràfic estàtic · Replay · Corba de capital · Estratègia (operacions)
"""
from __future__ import annotations

from pathlib import Path

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
from core.helpers import _df_to_csv_bytes, _logo_html
from core.strategy import (
    build_strategy_dataset,
    build_strategy_dataset_with_warmup,
    run_strategy_backtest,
    build_msci_etf_equity,
)
from ui.charts import (
    _build_strategy_chart_html,
    _build_replay_chart_html,
    _build_equity_curve_html,
)
from ui.components import (
    render_table,
    subtab_intro,
    render_page_header,
    _metrics_html,
    _strategy_summary_html,
)
from ui.styles import apply_global_styles
from core.fiscal import (
    compute_tax_summary, apply_tax_to_equity, sales_from_trades, TaxableSale, _to_date,
)
from ui.fiscal_ui import render_tax_controls, render_tax_kpis


def render_accio_individual(hist_path: Path, df_fund: pd.DataFrame) -> None:

    apply_global_styles()
    render_page_header(
        "Acció Individual",
        "Backtest tècnic per empresa amb Reversal Entry Zones + Dynamic Swing VWAP."
    )

    # La ruta dels històrics és fixa (HISTORICAL_PATH al top del fitxer).
    if not hist_path.exists():
        st.error(f"Carpeta no trobada: `{hist_path}`")
        return

    companies = (
        df_fund[["Ticker", "Companyia"]]
        .dropna(subset=["Ticker"])
        .drop_duplicates(subset=["Ticker"])
        .reset_index(drop=True)
    )
    opts = [f"{r['Ticker']}  —  {r['Companyia']}" for _, r in companies.iterrows()]

    sel = st.selectbox("Empresa:", opts, key="bt_sel_single", label_visibility="collapsed")
    ticker_sel = sel.split("  —  ")[0].strip()
    company_sel = sel.split("  —  ")[1].strip() if "  —  " in sel else ticker_sel

    # Targeta visual amb el logo de l'empresa seleccionada
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:14px;
                        background:linear-gradient(100deg,#0f172a 0%,#1e3a5f 100%);
                        border:1px solid #1e293b;border-radius:12px;
                        padding:12px 18px;margin:8px 0 14px 0;
                        box-shadow:0 2px 10px rgba(0,0,0,.25);">
          {_logo_html(ticker_sel, company_sel, size=44)}
          <div style="flex:1;min-width:0;">
            <div style="font-family:'DM Mono',monospace;font-size:.72rem;color:#60a5fa;
                         font-weight:700;letter-spacing:.08em;">{ticker_sel}</div>
            <div style="font-size:1.05rem;color:#f1f5f9;font-weight:600;line-height:1.2;margin-top:2px;">
              {company_sel}
            </div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

    with st.spinner(f"Carregant dades de {ticker_sel}…"):
        df_ohlc = load_ohlc(ticker_sel, hist_path, company_name=company_sel)

    if df_ohlc is None or df_ohlc.empty:
        st.warning(f"No s'ha trobat `{ticker_sel}` a `{hist_path}`")
        return

    d_min = df_ohlc["Date"].min().date()
    d_max = df_ohlc["Date"].max().date()
    # Per defecte: arrencar al període d'estudi del treball (clampat al
    # rang disponible de l'actiu). Les dades anteriors a STUDY_START_DATE
    # NO entren al backtest: queden com a warm-up dels indicadors.
    default_from = max(min(STUDY_START_DATE, d_max), d_min)
    default_to   = max(min(STUDY_END_DATE,   d_max), d_min)

    # Per defecte: període d'estudi del treball i 10.000€. Els controls
    # apareixeran com a targetes editables just després dels KPIs (sota).
    if "bt_from_single" not in st.session_state:
        st.session_state["bt_from_single"] = default_from
    if "bt_to_single" not in st.session_state:
        st.session_state["bt_to_single"] = default_to
    if "bt_capital_single" not in st.session_state:
        st.session_state["bt_capital_single"] = 10_000.0

    date_from = st.session_state["bt_from_single"]
    date_to = st.session_state["bt_to_single"]
    capital_input = st.session_state["bt_capital_single"]

    # Protecció: si l'actiu canvia i els valors guardats queden fora de rang
    if date_from < d_min or date_from > d_max:
        date_from = default_from
        st.session_state["bt_from_single"] = date_from
    if date_to < d_min or date_to > d_max:
        date_to = default_to
        st.session_state["bt_to_single"] = date_to

    if date_from >= date_to:
        st.warning("La data d'inici ha de ser anterior a la data final.")
        return

    # ── Controls inline: execució + position sizing (sense expander) ──
    st.markdown(
        "<div style='margin-top:6px;font-size:.72rem;color:#64748b;font-weight:600;"
        "text-transform:uppercase;letter-spacing:.06em;'>⏱️ Execució d'ordres</div>",
        unsafe_allow_html=True,
    )
    exec_c1, exec_c2 = st.columns([1, 2])
    with exec_c1:
        delay_bars = st.select_slider(
            "Barres de confirmació:",
            options=[0, 1, 2],
            value=0,
            key="delay_bars_single",
            format_func=lambda x: f"{x} barra(s)" + ("  [clàssic]" if x == 0 else ("  [realista]" if x == 1 else "  [conservador]")),
            help="0 = executa al Close del dia del senyal (clàssic, amb potencial look-ahead) · "
                 "1 = executa al Close del dia següent (realista, defecte recomanat a TradingView) · "
                 "2 = executa al Close del dia+2 (màxima confirmació).",
        )
    with exec_c2:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        st.caption(
            "💡 Amb retard >0, els criteris es calculen al dia del **senyal**, "
            "però l'ordre s'executa al **Close del dia d'execució**."
        )

    # ── Comissions (aplicades per igual a Estratègia i B&H per comparació justa) ──
    st.markdown(
        "<div style='margin-top:12px;font-size:.72rem;color:#94a3b8;font-weight:600;"
        "text-transform:uppercase;letter-spacing:.06em;'>💶 Costos de transacció</div>",
        unsafe_allow_html=True,
    )
    fee_c1, fee_c2, fee_c3 = st.columns([1, 1, 1])
    with fee_c1:
        fee_pct = st.slider(
            "Comissió per operació (%):",
            min_value=0.0, max_value=2.0, value=0.25, step=0.05,
            key="fee_pct_single",
            help="S'aplica tant a la COMPRA com a la VENDA, i tant a l'Estratègia "
                 "com al Buy & Hold i al ETF MSCI, perquè la comparació sigui justa. "
                 "Valor per defecte: 0.25% (típic de brokers retail).",
        )
    with fee_c2:
        bh_maint_pct = st.slider(
            "Manteniment anual B&H (%):",
            min_value=0.0, max_value=2.0, value=0.0, step=0.05,
            key="bh_maint_single",
            help="Cost de custòdia/manteniment anual aplicat NOMÉS al Buy & Hold "
                 "(prorratejat per dies mantinguts). Simula fees de gestió "
                 "d'un broker. L'estratègia activa no en paga perquè té rotació.",
        )
    with fee_c3:
        msci_ter_pct = st.slider(
            "TER anual MSCI World (%):",
            min_value=0.0, max_value=2.0, value=0.20, step=0.05,
            key="msci_ter_single",
            help="Total Expense Ratio anual de l'ETF que rèplica el MSCI World "
                 "(p.ex. iShares Core MSCI World: ~0.20%). Prorratejat per dies.",
        )

    mask = (df_ohlc["Date"].dt.date >= date_from) & (df_ohlc["Date"].dt.date <= date_to)
    df_period = df_ohlc.loc[mask].reset_index(drop=True)
    if len(df_period) < 30:
        st.warning("Període massa curt (mínim 30 sessions).")
        return

    st.markdown(_metrics_html(df_period), unsafe_allow_html=True)

    # ── Selectors de període + capital com a targetes (substitueix la barra
    # superior que hi havia abans). Mantenen l'estil visual dels KPIs. ──
    sel_c1, sel_c2, sel_c3 = st.columns(3, gap="small")
    with sel_c1:
        st.markdown(
            '<div style="font-size:.68rem;color:#94a3b8;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">📅 Des de</div>',
            unsafe_allow_html=True,
        )
        new_from = st.date_input(
            "Des de:", value=date_from, min_value=d_min, max_value=d_max,
            key="bt_from_single", label_visibility="collapsed",
        )
    with sel_c2:
        st.markdown(
            '<div style="font-size:.68rem;color:#94a3b8;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">📅 Fins a</div>',
            unsafe_allow_html=True,
        )
        new_to = st.date_input(
            "Fins a:", value=date_to, min_value=d_min, max_value=d_max,
            key="bt_to_single", label_visibility="collapsed",
        )
    with sel_c3:
        st.markdown(
            '<div style="font-size:.68rem;color:#94a3b8;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">💰 Capital inicial (€)</div>',
            unsafe_allow_html=True,
        )
        new_capital = st.number_input(
            "Capital inicial (€):",
            min_value=100.0, max_value=10_000_000.0,
            value=float(capital_input), step=1_000.0, format="%.2f",
            key="bt_capital_single", label_visibility="collapsed",
        )

    # Si algun ha canviat, refreshem
    if new_from != date_from or new_to != date_to or new_capital != capital_input:
        st.rerun()

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    cfg = StrategyConfig(
        capital_inicial=float(capital_input),
        entry_delay_bars=int(delay_bars),
        fee_buy_pct=float(fee_pct) / 100.0,
        fee_sell_pct=float(fee_pct) / 100.0,
        bh_annual_maintenance_pct=float(bh_maint_pct) / 100.0,
    )
    # WARM-UP + RESTRICCIÓ:
    # Es passa el df_ohlc COMPLET (no df_period) perquè els indicadors
    # tinguin un buffer de WARMUP_BUFFER_DAYS dies abans de date_from.
    # La funció torna el dataset ja retallat a [date_from, date_to],
    # de manera que run_strategy_backtest NO veu cap fila de warm-up
    # i és impossible que generi cap operació fora del període.
    ds = build_strategy_dataset_with_warmup(
        df_ohlc, cfg,
        trade_start=date_from, trade_end=date_to,
        warmup_days=WARMUP_BUFFER_DAYS,
    )
    result = run_strategy_backtest(ds, cfg)

    # ── FISCALITAT (nivell actiu individual) ───────────────────────────────
    # ATENCIÓ METODOLÒGICA: la base de l'estalvi de l'IRPF es calcula a
    # nivell de CARTERA (sumant tots els actius d'un any). Aquí, en analitzar
    # UN sol actiu, l'impost es calcula "com si aquest actiu fos l'única
    # inversió del contribuent". És una aproximació útil per veure l'efecte,
    # però el càlcul fiscalment vàlid és el de la pestanya Fiscalitat.
    with st.expander("🧾 Fiscalitat (IRPF · base de l'estalvi)"):
        st.caption(
            "⚠️ Càlcul orientatiu per a un sol actiu. La base de l'estalvi "
            "real és de cartera (suma de tots els valors); consulta la "
            "pestanya **Fiscalitat** per al càlcul vàlid."
        )
        tax_cfg = render_tax_controls(scope="accio", compact=True)

    # Liquidació de l'estratègia (vendes = operacions tancades)
    sales_strat = sales_from_trades(result["trades"], ticker_sel)
    tax_summary = compute_tax_summary(sales_strat, tax_cfg)

    # Liquidació del B&H: una única transmissió al final del període
    bh_sales = []
    try:
        bh_sales = [TaxableSale(
            ticker=ticker_sel,
            sell_date=_to_date(str(date_to)),
            buy_date=_to_date(str(date_from)),
            pnl=float(result["bh_capital_final"]) - float(result["capital_inicial"]),
        )]
    except Exception:
        pass
    bh_tax_summary = compute_tax_summary(bh_sales, tax_cfg)

    # Capitals nets d'impostos
    cap_brut = float(result["capital_final"])
    cap_net = cap_brut - tax_summary.total_tax
    bh_brut = float(result["bh_capital_final"])
    bh_net = bh_brut - bh_tax_summary.total_tax

    # ── Desat per a la pestanya FISCALITAT (mode actiu individual) ─────────
    # Si l'usuari no ha executat encara el Backtest de cartera, la pestanya
    # Fiscalitat pot caure en aquest paquet d'un sol actiu. Es marca amb
    # source="accio" perquè la pestanya avisi que el càlcul fiscalment
    # vàlid és el de cartera (la base de l'estalvi és global).
    st.session_state["fiscal_data_accio"] = {
        "source": "accio",
        "period": [str(date_from), str(date_to)],
        "capital_total": float(result["capital_inicial"]),
        "pf_equity_points": result["equity"],
        "pf_bh_equity_points": result.get("bh_equity", []),
        "assets": [{
            "ticker": ticker_sel,
            "company": company_sel,
            "trades": result["trades"],
            "equity": result["equity"],
            "bh_equity": result.get("bh_equity", []),
            "capital_inicial": float(result["capital_inicial"]),
            "capital_final": float(result["capital_final"]),
            "bh_capital_final": float(result["bh_capital_final"]),
            "period": [str(date_from), str(date_to)],
        }],
    }

    if tax_cfg.enabled:
        st.markdown(
            render_tax_kpis(
                capital_brut=cap_brut,
                capital_net=cap_net,
                total_tax=tax_summary.total_tax,
                total_disallowed=tax_summary.total_losses_disallowed,
                capital_inicial=float(result["capital_inicial"]),
            ),
            unsafe_allow_html=True,
        )

    # ── Visualització amb 4 sub-pestanyes ──
    view_tab1, view_tab2, view_tab3, view_tab4 = st.tabs([
        "📊 Gràfic estàtic (vista general)",
        "🎬 Replay animat (dia a dia amb criteris)",
        "📈 Corba de capital (vs B&H i MSCI World)",
        "⚡ Estratègia Reversal + DSVWAP (operacions)",
    ])
    with view_tab1:
        chart_html = _build_strategy_chart_html(result["dataset"], ticker_sel, company_sel, result)
        # Alçada generosa per encabir 3 panells (preu + volum + ATR%) + header/toolbar
        # Valors fixos perquè cap panell quedi tallat al render.
        cH = 480   # panell preu
        vH = 130   # panell volum
        aH = 150   # panell ATR%
        total_h = cH + vH + aH + 240  # +240 = header + view-tabs + toolbar + legend + paddings
        components.html(chart_html, height=total_h, scrolling=False)
    with view_tab2:
        st.markdown(
            "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:8px;line-height:1.5;'>"
            "Reprodueix el backtest <b>dia a dia</b>. Passa el ratolí sobre els marcadors de "
            "compra/venda per veure'n els criteris complerts. "
            "<br><b>Controls:</b> Play/Pausa (<kbd>Espai</kbd>) · Següent/Anterior operació (<kbd>N</kbd>/<kbd>P</kbd>) · "
            "Setmana a setmana (<kbd>←</kbd>/<kbd>→</kbd>) · Slider per anar a una data concreta."
            "</div>",
            unsafe_allow_html=True,
        )
        replay_html = _build_replay_chart_html(result["dataset"], ticker_sel, company_sel, result)
        # Alçada generosa per encabir 3 panells + header + controls del replay
        replay_h = 1100
        components.html(replay_html, height=replay_h, scrolling=False)
    with view_tab3:
        st.markdown(
            "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:8px;line-height:1.5;'>"
            "Comparativa <b>normalitzada a base 100</b> del capital al llarg del temps entre: "
            "estratègia aplicada a l'actiu, Buy & Hold del mateix actiu, i l'índex "
            "<b>MSCI World</b> com a referència global."
            "</div>",
            unsafe_allow_html=True,
        )
        # Carreguem el MSCI World (caché activa a load_msci_world)
        msci_df = load_msci_world(INDICES_PATH)
        if msci_df is None:
            st.markdown(
                f"<div style='padding:8px 14px;background:#fef3c7;border:1px solid #fcd34d;"
                f"border-radius:8px;font-size:.8rem;color:#92400e;margin-bottom:10px;'>"
                f"⚠️ No s'ha trobat <code>{MSCI_WORLD_FILENAME}</code> a <code>{INDICES_PATH}</code>. "
                f"Es mostraran només les corbes Estratègia i B&amp;H."
                f"</div>",
                unsafe_allow_html=True,
            )
        # Retallem el MSCI al període del backtest
        msci_period = None
        if msci_df is not None:
            msci_period = msci_df[
                (msci_df["Date"].dt.date >= date_from) & (msci_df["Date"].dt.date <= date_to)
            ].copy().reset_index(drop=True)
            if msci_period.empty:
                msci_period = None

        # FISCALITAT: si està activa, la corba de l'estratègia es mostra
        # neta d'impostos (cau en graons cada 31/12 amb tributació). La
        # línia B&H del gràfic es deixa bruta perquè es deriva de
        # df_period["Close"] (preus); el seu impacte fiscal, en diferir-se
        # al final, es veu millor a la pestanya Fiscalitat.
        #
        # MSCI WORLD: es modela com a ETF amb comissions + TER + IRPF a la
        # venda final. Així la corba és directament comparable a les altres.
        curve_equity = result["equity"]
        if tax_cfg.enabled:
            curve_equity = apply_tax_to_equity(result["equity"], tax_summary.yearly)

        msci_curve_df_single = None
        if msci_period is not None and not msci_period.empty:
            msci_etf_single = build_msci_etf_equity(
                msci_period,
                capital_inicial=float(cfg.capital_inicial),
                fee_pct=float(fee_pct) / 100.0,
                slippage_buy_pct=0.0,
                slippage_sell_pct=0.0,
                ter_annual_pct=float(msci_ter_pct) / 100.0,
            )
            msci_equity_pts_single = msci_etf_single["equity"]
            if tax_cfg.enabled and msci_equity_pts_single:
                msci_pnl_s = (msci_etf_single["capital_final"]
                              - msci_etf_single["capital_inicial"])
                msci_sales_s = [TaxableSale(
                    ticker="MSCI_WORLD",
                    sell_date=_to_date(str(date_to)),
                    buy_date=_to_date(str(date_from)),
                    pnl=msci_pnl_s,
                )]
                msci_tax_s = compute_tax_summary(msci_sales_s, tax_cfg)
                msci_equity_pts_single = apply_tax_to_equity(
                    msci_equity_pts_single, msci_tax_s.yearly
                )
            if msci_equity_pts_single:
                msci_curve_df_single = pd.DataFrame([
                    {"Date": p["time"], "Close": p["value"]}
                    for p in msci_equity_pts_single
                ])
                # IMPORTANT: _resample_index_to_dates (cridada des de
                # _build_equity_curve_html) usa l'accessor .dt sobre la
                # columna Date, que requereix tipus datetime. Convertim
                # explícitament les strings dels equity points a Timestamp.
                msci_curve_df_single["Date"] = pd.to_datetime(
                    msci_curve_df_single["Date"]
                )

        equity_html = _build_equity_curve_html(
            equity_points=curve_equity,
            prices_df=df_period[["Date", "Close"]],
            msci_df=msci_curve_df_single,
            capital_inicial=float(cfg.capital_inicial),
            title=f"Corba de capital — {ticker_sel} · {company_sel}",
            subtitle=f"{date_from} → {date_to}"
                     + (" · net d'IRPF" if tax_cfg.enabled else ""),
        )
        components.html(equity_html, height=720, scrolling=False)

    with view_tab4:
        st.markdown(
            "<div style='font-size:.82rem;color:#cbd5e1;margin-bottom:8px;line-height:1.5;'>"
            "Resum complet del backtest amb els KPIs principals i l'<b>historial detallat "
            "de totes les operacions</b> executades (entrades, sortides, fracció invertida, "
            "accions, capital, retorn per operació…). També pots descarregar-ho com a CSV."
            "</div>",
            unsafe_allow_html=True,
        )
        summary_html = _strategy_summary_html(result, ticker_sel, str(date_from), str(date_to))
        summary_h = 260 + min(result["n_trades"] * 38 + 120, 460)
        components.html(summary_html, height=summary_h, scrolling=False)

        # ── Botó descàrrega CSV de l'historial d'operacions ──
        if result["trades"]:
            df_trades_dl = pd.DataFrame(result["trades"])
            csv_trades = _df_to_csv_bytes(df_trades_dl)
            dl_c1, dl_c2 = st.columns([1, 3])
            with dl_c1:
                st.download_button(
                    label="📥 Descarregar historial (CSV)",
                    data=csv_trades,
                    file_name=f"historial_{ticker_sel}_{date_from}_{date_to}.csv",
                    mime="text/csv",
                    key=f"dl_hist_{ticker_sel}",
                    use_container_width=True,
                )
            with dl_c2:
                st.markdown(
                    f"<div style='padding:8px 12px;font-size:.78rem;color:#64748b;'>"
                    f"📊 {len(result['trades'])} operacions · "
                    f"Capital invertit complet (100% a cada compra)</div>",
                    unsafe_allow_html=True,
                )


# ─────────────────────────────────────────────────────────────
# PONDERACIÓ DE CARTERA — PES DIRECTE DE LA CLASSIFICACIÓ
# ─────────────────────────────────────────────────────────────
