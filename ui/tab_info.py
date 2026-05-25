"""
Pestanya 'Informació Cartera':
  • Llistat de les 30 empreses amb logos
  • Detall complet d'una empresa (fonamentals + indicadors + classificació)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core.config import (
    FUNDAMENTALS_COLUMNS,
    COMMON_INDICATORS_COLUMNS,
    INDUSTRIAL_INDICATORS_COLUMNS,
    FINANCIAL_INDICATORS_COLUMNS,
)
from core.data_io import (
    load_top30_data,
    normalize_columns,
    safe_select_columns,
)
from core.helpers import _logo_html, _load_logo_b64
from ui.components import render_table, subtab_intro, render_page_header
from ui.styles import apply_global_styles


def _get_row(df: pd.DataFrame, ticker: str) -> dict:
    """Retorna la fila de l'empresa com a dict, o {} si no existeix."""
    for col in ("Ticker", "ticker", "TICKER"):
        if col in df.columns:
            match = df[df[col].astype(str).str.strip().str.upper() == ticker.upper()]
            if not match.empty:
                row = match.iloc[0].to_dict()
                return {k: (None if pd.isna(v) or str(v).strip() in {"", "nan", "None", "<NA>"} else str(v).strip())
                        for k, v in row.items()}
    return {}


def render_info_empresa(
    df_fund, df_ind_comu, df_ind_ind, df_ind_fin,
    df_sc_comu, df_sc_ind, df_sc_fin,
    df_sp_comu, df_sp_ind, df_sp_fin,
    df_final,
) -> None:

    STATE_KEY = "ic_empresa_ticker"
    if STATE_KEY not in st.session_state:
        st.session_state[STATE_KEY] = None

    # Preparem la llista d'empreses
    companies = (
        df_fund[["Ticker", "Companyia", "Sector", "Pais"]]
        .dropna(subset=["Ticker"])
        .drop_duplicates(subset=["Ticker"])
        .reset_index(drop=True)
    )
    tickers_list = [str(r["Ticker"]).strip() for _, r in companies.iterrows()]
    names_list   = [str(r["Companyia"]).strip() for _, r in companies.iterrows()]

    selected = st.session_state[STATE_KEY]

    # ── CSS cards ────────────────────────────────────────
    st.markdown("""
    <style>
    /* ── Columnes empresa: amplada exactament igual ── */
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        flex: 1 1 0% !important;
        min-width: 0 !important;
    }

    /* ── Targetes empresa: mida fixa i text visible ── */
    div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
        width: 100% !important;
        height: 88px !important;
        min-height: 88px !important;
        max-height: 88px !important;
        background: var(--surface-1, #111111) !important;
        border: 1.5px solid var(--border-1, #2a2a2a) !important;
        border-radius: 12px !important;
        padding: 12px 14px !important;
        text-align: left !important;
        font-family: 'DM Sans', sans-serif !important;
        font-size: .81rem !important;
        color: var(--text-primary, #f1f5f9) !important;
        cursor: pointer !important;
        transition: all .16s !important;
        box-shadow: 0 1px 4px rgba(0,0,0,.4) !important;
        overflow: hidden !important;
        white-space: pre-wrap !important;
        line-height: 1.4 !important;
    }
    div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button:hover {
        border-color: var(--accent-blue, #3b82f6) !important;
        box-shadow: 0 4px 14px rgba(59,130,246,.3) !important;
        transform: translateY(-2px) !important;
        background: var(--surface-2, #1a1a1a) !important;
    }
    div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button p,
    div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button span,
    div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button div {
        color: var(--text-primary, #f1f5f9) !important;
        font-size: inherit !important;
        white-space: inherit !important;
        overflow: hidden !important;
    }
    </style>""", unsafe_allow_html=True)

    # ── Vista de llista d'empreses ────────────────────────
    if selected is None:
        subtab_intro("Selecciona una empresa per veure totes les seves dades en mode resum.")

        # Pre-carreguem tots els logos i construïm un sol bloc CSS
        # ── Logos i alineament uniforme ──
        # ENFOCAMENT (que sí funciona):
        #
        # Streamlit renderitza la graella com una sèrie d'`stHorizontalBlock`
        # cadascú amb 5 columnes. Cada columna té un `stButton` a dins.
        # Posició lineal del botó número N (0-indexed):
        #     fila    = N // 5
        #     columna = N % 5
        # 
        # Per apuntar a CADA botó concret, fem servir un selector via
        # `nth-of-type(fila+1)` sobre stHorizontalBlock + `nth-of-type(col+1)`
        # sobre stColumn. Aquesta jerarquia ÉS estable a Streamlit.
        cols = st.columns(5, gap="small")

        # Pre-carreguem TOTS els logos abans de pintar (cache evita relectures)
        logo_uris = []
        for _, row in companies.iterrows():
            ticker_c = str(row["Ticker"]).strip()
            name_c   = str(row["Companyia"]).strip()
            logo_uris.append(_load_logo_b64(ticker_c, name_c))

        # ── REGLES CSS BASE (alineament uniforme i cercle negre) ──
        css_rules = ["""
        /* Tots els botons de la graella d'empreses: padding-left fix + alineament
           del text a l'esquerra perquè totes les targetes comencin igual */
        div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
            padding-left: 56px !important;
            text-align: left !important;
        }
        div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button > div,
        div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button p {
            text-align: left !important;
            margin-left: 0 !important;
        }
        """]

        # ── REGLES INDIVIDUALS PER CADA POSICIÓ ──
        # Streamlit assigna `key="emp_{i}"` a cada botó. La manera més robusta
        # de targetar-lo és per la classe automàtica que Streamlit afegeix:
        # `class="st-key-emp_{i}"` sobre el div container.
        for i, uri in enumerate(logo_uris):
            if not uri:
                continue
            css_rules.append(f"""
            .st-key-emp_{i} button {{
                background:
                    url('{uri}') no-repeat 14px center / 26px 26px,
                    radial-gradient(circle 17px at 27px 50%,
                        #000 0%,
                        #000 90%,
                        rgba(148,163,184,.35) 92%,
                        rgba(148,163,184,.35) 100%,
                        transparent 101%),
                    #111111 !important;
                background-color: #111111 !important;
            }}
            .st-key-emp_{i} button:hover {{
                background:
                    url('{uri}') no-repeat 14px center / 26px 26px,
                    radial-gradient(circle 17px at 27px 50%,
                        #000 0%,
                        #000 90%,
                        rgba(96,165,250,.6) 92%,
                        rgba(96,165,250,.6) 100%,
                        transparent 101%),
                    #1a1a1a !important;
                background-color: #1a1a1a !important;
            }}""")

        st.markdown(f"<style>{''.join(css_rules)}</style>", unsafe_allow_html=True)

        # Graella de targetes
        for i, row in companies.iterrows():
            ticker_c = str(row["Ticker"]).strip()
            name_c   = str(row["Companyia"]).strip()
            sector_c = str(row["Sector"]).strip()
            label    = f"{ticker_c}\n{name_c}\n{sector_c}"
            with cols[i % 5]:
                if st.button(label, key=f"emp_{i}", use_container_width=True):
                    st.session_state[STATE_KEY] = ticker_c
                    st.rerun()
        return

    # ── Vista de detall d'empresa ────────────────────────
    ticker = selected

    # Barra superior: botó tornar + selector d'empresa
    nav_col, sel_col = st.columns([1, 4])
    with nav_col:
        if st.button("← Llista", key="back_btn"):
            st.session_state[STATE_KEY] = None
            st.rerun()
    with sel_col:
        # Selector per anar directament a una altra empresa
        options = [f"{t}  —  {n}" for t, n in zip(tickers_list, names_list)]
        current_idx = tickers_list.index(ticker) if ticker in tickers_list else 0
        chosen = st.selectbox(
            "Navegar a una altra empresa:",
            options=options,
            index=current_idx,
            key="emp_nav_select",
            label_visibility="collapsed",
        )
        chosen_ticker = chosen.split("  —  ")[0].strip()
        if chosen_ticker != ticker:
            st.session_state[STATE_KEY] = chosen_ticker
            st.rerun()

    # Recollim totes les dades
    d_fund    = _get_row(df_fund,     ticker)
    d_ic      = _get_row(df_ind_comu, ticker)
    d_ii      = _get_row(df_ind_ind,  ticker)
    d_if_     = _get_row(df_ind_fin,  ticker)
    d_sc      = _get_row(df_sc_comu,  ticker)
    d_si      = _get_row(df_sc_ind,   ticker)
    d_sf      = _get_row(df_sc_fin,   ticker)
    d_sp      = _get_row(df_sp_comu,  ticker)
    d_spi     = _get_row(df_sp_ind,   ticker)
    d_spf     = _get_row(df_sp_fin,   ticker)
    d_fin     = _get_row(df_final,    ticker)

    company_name = d_fund.get("Companyia", ticker)
    SKIP = {"Ticker", "Companyia"}
    is_financial = bool({k: v for k, v in d_if_.items() if k not in SKIP and v is not None})

    def _kv(fields, skip=None):
        skip = skip or set()
        rows = []
        for k, v in fields.items():
            if k in skip or v is None:
                continue
            rows.append(
                "<div class=\"kv-row\"><span class=\"kv-key\">" + k +
                "</span><span class=\"kv-val\">" + v + "</span></div>"
            )
        return "".join(rows)

    def _card(title, icon, content, extra=""):
        if not content.strip():
            return ""
        cls = "card " + extra if extra else "card"
        return (
            "<div class=\"" + cls + "\">"
            "<div class=\"card-head\"><span class=\"card-icon\">" + icon + "</span>"
            "<span class=\"card-title\">" + title + "</span></div>"
            "<div class=\"card-body\">" + content + "</div>"
            "</div>"
        )

    def _pill(label, val):
        if not val:
            return ""
        return (
            "<div class=\"id-pill\">"
            "<span class=\"id-label\">" + label + "</span>"
            "<span class=\"id-val\">" + val + "</span>"
            "</div>"
        )

    id_html = "".join([
        _pill("Sector",       d_fund.get("Sector")),
        _pill("Indústria",    d_fund.get("Indústria")),
        _pill("Continent",    d_fund.get("Continent")),
        _pill("País",         d_fund.get("Pais")),
        _pill("Moneda",       d_fund.get("Moneda")),
        _pill("Ticker Yahoo", d_fund.get("Ticker Yahoo")),
        _pill("Preu",         d_fund.get("Preu")),
        _pill("Valor mercat", d_fund.get("Valor de mercat")),
    ])

    is_c = _kv({"Ingressos": d_fund.get("Ingressos"),
                "Benefici Net": d_fund.get("Benefici Net"),
                "Benefici Operatiu": d_fund.get("Benefici Operatiu"),
                "EBITDA": d_fund.get("EBITDA"),
                "EPS_t": d_fund.get("EPS_t"),
                "EPS_(t-1)": d_fund.get("EPS_(t-1)")})
    bs_c = _kv({"Patrimoni Net": d_fund.get("Patrimoni Net"),
                "Deute total": d_fund.get("Deute total"),
                "Actiu Corrent": d_fund.get("Actiu Corrent"),
                "Passiu Corrent": d_fund.get("Passiu Corrent"),
                "Enterprise Value": d_fund.get("Enterprise Value")})
    cf_c = _kv({"Cash + Short Term Investments": d_fund.get("Cash + Short Term Investments"),
                "Cash Flow Operatiu": d_fund.get("Cash Flow Operatiu"),
                "CAPEX": d_fund.get("CAPEX")})

    row1 = (
        "<div class=\"row3\">" +
        _card("Income Statement", "📈", is_c) +
        _card("Balance Sheet",    "🏛️", bs_c) +
        _card("Cash & Flows",     "💧", cf_c) +
        "</div>"
    )
    row2 = (
        "<div class=\"row3\">" +
        _card("Indicadors comuns",     "📐", _kv(d_ic,  SKIP)) +
        _card("Scoring comú",          "🎯", _kv(d_sc,  SKIP)) +
        _card("Scoring ponderat comú", "⚖️", _kv(d_sp,  SKIP)) +
        "</div>"
    )
    if is_financial:
        row3 = (
            "<div class=\"row3\">" +
            _card("Indicadors financers",      "🏦", _kv(d_if_, SKIP)) +
            _card("Scoring financer",          "🎯", _kv(d_sf,  SKIP)) +
            _card("Scoring ponderat financer", "⚖️", _kv(d_spf, SKIP)) +
            "</div>"
        )
    else:
        row3 = (
            "<div class=\"row3\">" +
            _card("Indicadors industrials",      "⚙️", _kv(d_ii,  SKIP)) +
            _card("Scoring industrial",          "🎯", _kv(d_si,  SKIP)) +
            _card("Scoring ponderat industrial", "⚖️", _kv(d_spi, SKIP)) +
            "</div>"
        )

    fin_fields = {k: v for k, v in d_fin.items() if k not in SKIP and v is not None}
    row4 = _card("Classificació Final", "🏆", _kv(fin_fields), extra="card-final")

    full_html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:'DM Sans',sans-serif; background:#000; padding:4px 2px 12px; color:#f1f5f9; }

  .hero {
    background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 50%,#1d4ed8 100%);
    border-radius:14px; padding:20px 28px 18px;
    margin-bottom:12px; position:relative; overflow:hidden;
  }
  .hero::after {
    content:''; position:absolute; top:-60px; right:-60px;
    width:260px; height:260px; background:rgba(255,255,255,.03); border-radius:50%;
  }
  .hero-top { display:flex; align-items:center; gap:16px; margin-bottom:12px; }
  .hero-titles { display:flex; flex-direction:column; gap:3px; min-width:0; }
  .hero-ticker {
    font-family:'DM Mono',monospace; font-size:.78rem; font-weight:500;
    color:#60a5fa; letter-spacing:.12em; text-transform:uppercase;
  }
  .hero-name { font-size:1.45rem; font-weight:700; color:#fff; letter-spacing:-.02em; }
  .id-pills  { display:flex; flex-wrap:wrap; gap:7px; }
  .id-pill {
    display:flex; align-items:center; gap:6px;
    background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.15);
    border-radius:20px; padding:4px 12px;
  }
  .id-label { font-size:.66rem; color:#94a3b8; font-weight:600; text-transform:uppercase; letter-spacing:.05em; }
  .id-val   { font-size:.78rem; color:#e2e8f0; font-weight:600; font-family:'DM Mono',monospace; }

  .row3 { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:10px; }

  .card {
    background:#111111; border:1px solid #2a2a2a; border-radius:12px;
    overflow:hidden; box-shadow:0 2px 6px rgba(0,0,0,.4);
    display:flex; flex-direction:column;
  }
  .card-head {
    background:linear-gradient(90deg,#0f172a,#1e293b);
    border-bottom:1px solid #2a2a2a;
    padding:9px 16px; display:flex; align-items:center; gap:8px; flex-shrink:0;
  }
  .card-icon  { font-size:.95rem; }
  .card-title { font-size:.85rem; font-weight:700; color:#f1f5f9; }
  .card-body  { padding:10px 16px 12px; flex:1; }

  /* Files clau-valor: alineament uniforme amb columnes fixes */
  .kv-row {
    display:grid;
    grid-template-columns: 1fr auto;
    align-items:baseline;
    padding:5px 0; border-bottom:1px solid #1f2937; gap:14px;
  }
  .kv-row:last-child { border-bottom:none; }
  .kv-key {
    font-size:.77rem; color:#94a3b8; font-weight:500;
    line-height:1.3; text-align:left;
  }
  .kv-val {
    font-family:'DM Mono',monospace; font-size:.8rem; color:#f1f5f9;
    font-weight:600; text-align:right; white-space:nowrap;
  }

  .card-final { margin-top:2px; border-color:#3b82f6; box-shadow:0 2px 14px rgba(59,130,246,.25); }
  .card-final .card-head {
    background:linear-gradient(90deg,#1e3a5f,#1d4ed8);
    border-bottom-color:#1d4ed8;
  }
  .card-final .card-icon,
  .card-final .card-title { color:#fff !important; }
  .card-final .card-body {
    display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
    gap:0 28px; padding:12px 18px 14px;
  }
  .card-final .kv-key { color:#475569; }
  .card-final .kv-val { color:#1d4ed8; font-size:.85rem; }
</style>
</head>
<body>
  <div class="hero">
    <div class="hero-top">
      """ + _logo_html(ticker, company_name, size=48, style_extra="margin-right:4px;") + """
      <div class="hero-titles">
        <span class="hero-ticker">""" + ticker + """</span>
        <span class="hero-name">""" + company_name + """</span>
      </div>
    </div>
    <div class="id-pills">""" + id_html + """</div>
  </div>
  """ + row1 + row2 + row3 + row4 + """
</body>
</html>"""

    components.html(full_html, height=1800, scrolling=True)

# ============================================================
# PÀGINA PRINCIPAL
# ============================================================
def render_informacio_cartera(base_path: str | Path = ".") -> None:
    apply_global_styles()
    render_page_header(
        "Informació Cartera",
        "Vista estructurada de fonamentals, indicadors, scoring, scoring ponderat i classificació final de la cartera.",
    )

    base_path = Path(base_path)

    file_map = {
        "fonamentals":          base_path / "Top30_FONAMENTALS.csv",
        "indicadors_comu":      base_path / "Top30_INDICADORS_COMU.csv",
        "indicadors_espec_ind": base_path / "Top30_INDICADORS_ESPEC_IND.csv",
        "indicadors_espec_fin": base_path / "Top30_INDICADORS_ESPEC_FIN.csv",
        "scoring_comu":         base_path / "Top30_SCORING_COMU.csv",
        "scoring_espec_ind":    base_path / "Top30_SCORING_ESPEC_IND.csv",
        "scoring_espec_fin":    base_path / "Top30_SCORING_ESPEC_FIN.csv",
        "scoring_pond_comu":    base_path / "Top30_SCORING_POND_COMU.csv",
        "scoring_pond_espec_ind": base_path / "Top30_SCORING_POND_ESPEC_IND.csv",
        "scoring_pond_espec_fin": base_path / "Top30_SCORING_POND_ESPEC_FIN.csv",
        "classificacio_final":  base_path / "Top30_CLASSIFICACIO_FINAL.csv",
    }

    missing = [p.name for p in file_map.values() if not p.exists()]
    if missing:
        st.error("Falten els següents fitxers CSV a la carpeta del bot:")
        st.write(missing)
        st.info(f"Ruta actual de cerca: {base_path.resolve()}")
        return

    # Càrrega
    df_fund      = safe_select_columns(load_top30_data(file_map["fonamentals"]),          FUNDAMENTALS_COLUMNS)
    df_ind_comu  = safe_select_columns(load_top30_data(file_map["indicadors_comu"]),      COMMON_INDICATORS_COLUMNS)
    df_ind_ind   = safe_select_columns(load_top30_data(file_map["indicadors_espec_ind"]), INDUSTRIAL_INDICATORS_COLUMNS)
    df_ind_fin   = safe_select_columns(load_top30_data(file_map["indicadors_espec_fin"]), FINANCIAL_INDICATORS_COLUMNS)
    df_sc_comu   = normalize_columns(load_top30_data(file_map["scoring_comu"]))
    df_sc_ind    = normalize_columns(load_top30_data(file_map["scoring_espec_ind"]))
    df_sc_fin    = normalize_columns(load_top30_data(file_map["scoring_espec_fin"]))
    df_sp_comu   = normalize_columns(load_top30_data(file_map["scoring_pond_comu"]))
    df_sp_ind    = normalize_columns(load_top30_data(file_map["scoring_pond_espec_ind"]))
    df_sp_fin    = normalize_columns(load_top30_data(file_map["scoring_pond_espec_fin"]))
    df_final     = normalize_columns(load_top30_data(file_map["classificacio_final"]))

    # Sub-pestanyes
    tabs = st.tabs([
        "🏢  Informació empresa",
        "📋  Fonamentals",
        "📐  Indicadors",
        "🎯  Scoring",
        "⚖️  Scoring ponderat",
        "🏆  Classificació Final",
    ])

    # ── Informació empresa ───────────────────────────────────
    with tabs[0]:
        render_info_empresa(
            df_fund, df_ind_comu, df_ind_ind, df_ind_fin,
            df_sc_comu, df_sc_ind, df_sc_fin,
            df_sp_comu, df_sp_ind, df_sp_fin,
            df_final,
        )

    # ── Fonamentals ──────────────────────────────────────────
    with tabs[1]:
        subtab_intro("Dades base de les empreses que formen part de la cartera.")
        render_table(
            "Fonamentals",
            df_fund,
            subtitle="Informació descriptiva i financera principal de les empreses seleccionades.",
            height_class="tall",
        )

    # ── Indicadors ───────────────────────────────────────────
    with tabs[2]:
        subtab_intro("Separació dels indicadors comuns i específics segons el tipus d'empresa.")
        render_table(
            "Taula 1 · Part comuna",
            df_ind_comu,
            subtitle="Indicadors generals compartits per totes les empreses de la cartera.",
        )
        render_table(
            "Taula 2 · Part específica — Industrials",
            df_ind_ind,
            subtitle="Indicadors específics aplicats a empreses industrials i no financeres.",
        )
        render_table(
            "Taula 3 · Part específica — Financeres",
            df_ind_fin,
            subtitle="Indicadors específics aplicats exclusivament al sector financer.",
            height_class="short",
        )

    # ── Scoring ──────────────────────────────────────────────
    with tabs[3]:
        subtab_intro("Conversió dels indicadors en puntuacions comparables dins del model.")
        render_table(
            "Taula 1 · Part comuna",
            df_sc_comu,
            subtitle="Valoració individual dels indicadors comuns abans de ponderar-los.",
        )
        render_table(
            "Taula 2 · Part específica — Industrials",
            df_sc_ind,
            subtitle="Scoring específic per a empreses industrials i no financeres.",
        )
        render_table(
            "Taula 3 · Part específica — Financeres",
            df_sc_fin,
            subtitle="Scoring específic per a entitats financeres.",
            height_class="short",
        )

    # ── Scoring ponderat ─────────────────────────────────────
    with tabs[4]:
        subtab_intro("Aplicació dels pesos definits per obtenir la contribució real de cada criteri.")
        render_table(
            "Taula 1 · Part comuna",
            df_sp_comu,
            subtitle="Scoring comú un cop aplicats els pesos definits al model.",
        )
        render_table(
            "Taula 2 · Part específica — Industrials",
            df_sp_ind,
            subtitle="Scoring ponderat específic per a empreses industrials i no financeres.",
        )
        render_table(
            "Taula 3 · Part específica — Financeres",
            df_sp_fin,
            subtitle="Scoring ponderat específic per a entitats financeres.",
            height_class="short",
        )

    # ── Classificació Final ──────────────────────────────────
    with tabs[5]:
        subtab_intro("Resultat final de la metodologia d'avaluació de la cartera.")
        render_table(
            "Classificació Final",
            df_final,
            subtitle="Resultat final ordenat segons la puntuació global de cada empresa.",
        )
