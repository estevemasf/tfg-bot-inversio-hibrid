"""
Estils CSS globals: paleta fosca, tabs, targetes, taules, hero, etc.
"""
from __future__ import annotations

import streamlit as st


def apply_global_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

        /* ═══════════════════════════════════════════════════════
           MODE FOSC GLOBAL — variables de color
           Inspirat pel negre pur del fons dels logos.
           ═══════════════════════════════════════════════════════ */
        :root {
            --bg-body:       #000000;    /* fons app (negre pur) */
            --bg-page:       #0a0a0a;    /* zones de contingut */
            --surface-1:     #111111;    /* targetes i panells */
            --surface-2:     #1a1a1a;    /* cards interiors, inputs */
            --surface-3:     #242424;    /* hover */
            --border-1:      #2a2a2a;    /* borders normals */
            --border-2:      #3a3a3a;    /* borders accentuats */
            --text-primary:  #f1f5f9;    /* text principal */
            --text-secondary:#cbd5e1;    /* text secundari */
            --text-muted:    #94a3b8;    /* text apagat */
            --accent-blue:   #3b82f6;
            --accent-blue-l: #60a5fa;
            --accent-green:  #10b981;
            --accent-red:    #ef4444;
            --accent-amber:  #f59e0b;
            --accent-purple: #8b5cf6;
        }

        /* ── Reset i fons de tota l'app ── */
        html, body, [class*="css"] {
            font-family: 'DM Sans', sans-serif !important;
            background: var(--bg-body) !important;
            color: var(--text-primary) !important;
        }
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            background: var(--bg-body) !important;
        }
        [data-testid="stHeader"] {
            background: transparent !important;
        }
        /* Text general */
        p, span, div, label {
            color: var(--text-primary);
        }
        /* Text dels captions i ajudes */
        .stCaption, [data-testid="stCaptionContainer"], small {
            color: var(--text-muted) !important;
        }
        /* Alerts/warnings amb fons fosc */
        [data-testid="stAlert"] {
            background: var(--surface-1) !important;
            border: 1px solid var(--border-1) !important;
            color: var(--text-primary) !important;
        }
        /* Text dins de les alerts */
        [data-testid="stAlert"] p,
        [data-testid="stAlert"] div {
            color: var(--text-primary) !important;
        }
        /* ── Inputs (text, number, date, select) amb fons fosc ── */
        [data-baseweb="input"],
        [data-baseweb="select"],
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div,
        div[data-testid="stDateInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input,
        div[data-testid="stSelectbox"] div[role="combobox"] {
            background: var(--surface-2) !important;
            color: var(--text-primary) !important;
            border-color: var(--border-1) !important;
        }
        div[data-testid="stDateInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input {
            border: 1px solid var(--border-1) !important;
            border-radius: 8px !important;
        }
        /* Select dropdown panell */
        div[data-baseweb="popover"] {
            background: var(--surface-2) !important;
        }
        div[data-baseweb="menu"] {
            background: var(--surface-2) !important;
            border: 1px solid var(--border-1) !important;
        }
        div[data-baseweb="menu"] li {
            color: var(--text-primary) !important;
        }
        div[data-baseweb="menu"] li:hover {
            background: var(--surface-3) !important;
        }
        /* Sliders */
        [data-baseweb="slider"] {
            color: var(--text-primary) !important;
        }
        /* Botons de download / download_button */
        [data-testid="stDownloadButton"] > button,
        [data-testid="stBaseButton-secondary"] {
            background: var(--surface-2) !important;
            color: var(--text-primary) !important;
            border: 1px solid var(--border-1) !important;
        }
        [data-testid="stDownloadButton"] > button:hover,
        [data-testid="stBaseButton-secondary"]:hover {
            background: var(--surface-3) !important;
            border-color: var(--accent-blue) !important;
        }
        /* Checkbox wrapper */
        [data-testid="stCheckbox"] label {
            color: var(--text-primary) !important;
        }
        /* Labels dels inputs */
        [data-testid="stWidgetLabel"] {
            color: var(--text-secondary) !important;
        }
        /* ═══════════════════════════════════════════════════════ */

        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 2rem !important;
            max-width: 98rem !important;
        }

        /* ── Capçalera de pàgina ── */
        .page-header {
            background: linear-gradient(135deg, #0b1120 0%, #1e3a5f 50%, #3b0764 100%);
            border-radius: 20px;
            padding: 32px 36px 28px 36px;
            margin-bottom: 28px;
            position: relative;
            overflow: hidden;
            box-shadow: 0 12px 40px rgba(15, 23, 42, 0.25),
                        inset 0 1px 0 rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(59, 130, 246, 0.15);
        }
        .page-header::before {
            content: '';
            position: absolute;
            top: -80px; right: -80px;
            width: 320px; height: 320px;
            background: radial-gradient(circle,
                rgba(59, 130, 246, 0.15) 0%,
                rgba(139, 92, 246, 0.08) 40%,
                transparent 70%);
            border-radius: 50%;
            pointer-events: none;
        }
        .page-header::after {
            content: '';
            position: absolute;
            bottom: -40px; left: -40px;
            width: 200px; height: 200px;
            background: radial-gradient(circle,
                rgba(139, 92, 246, 0.12) 0%,
                transparent 65%);
            border-radius: 50%;
            pointer-events: none;
        }
        .page-header-title {
            font-size: 1.9rem;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: -0.025em;
            margin: 0 0 8px 0;
            position: relative;
            z-index: 1;
            text-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
        }
        .page-header-subtitle {
            font-size: 0.96rem;
            color: #cbd5e1;
            margin: 0;
            font-weight: 400;
            position: relative;
            z-index: 1;
            line-height: 1.5;
        }
        .page-header-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: linear-gradient(135deg,
                rgba(59, 130, 246, 0.2) 0%,
                rgba(139, 92, 246, 0.15) 100%);
            border: 1px solid rgba(59, 130, 246, 0.35);
            color: #93c5fd;
            font-size: 0.72rem;
            font-weight: 700;
            padding: 5px 14px;
            border-radius: 20px;
            margin-bottom: 14px;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            position: relative;
            z-index: 1;
            box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
        }

        /* ── Pestanyes natives Streamlit ── */

        /* ═══════════════════════════════════════════════════════
           BARRA DE TABS PRINCIPAL (nivell 1)
           Disseny: gradient profund + pill de selecció amb glow
           ═══════════════════════════════════════════════════════ */
        div[data-testid="stTabs"] > div[role="tablist"] {
            position: sticky !important;
            top: 0 !important;
            z-index: 999 !important;
            background: linear-gradient(180deg, #0b1120 0%, #0f172a 100%) !important;
            border-bottom: 1px solid rgba(59, 130, 246, 0.25) !important;
            box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45),
                        inset 0 -1px 0 rgba(59, 130, 246, 0.08) !important;
            min-height: 54px !important;
            display: flex !important;
            align-items: center !important;
            padding: 0 10px !important;
            gap: 4px !important;
            scrollbar-width: none !important;
        }
        div[data-testid="stTabs"] > div[role="tablist"]::-webkit-scrollbar {
            display: none !important;
        }

        /* Línia animada d'accent sota la barra */
        div[data-testid="stTabs"] > div[role="tablist"]::after {
            content: '' !important;
            position: absolute !important;
            bottom: 0 !important; left: 0 !important; right: 0 !important;
            height: 1px !important;
            background: linear-gradient(90deg,
                transparent 0%,
                rgba(59, 130, 246, 0.4) 20%,
                rgba(139, 92, 246, 0.4) 50%,
                rgba(59, 130, 246, 0.4) 80%,
                transparent 100%) !important;
            pointer-events: none !important;
        }

        /* Botons de tab — estil pill moderns */
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"] {
            font-family: 'DM Sans', sans-serif !important;
            font-size: 0.9rem !important;
            font-weight: 600 !important;
            color: #94a3b8 !important;
            background: transparent !important;
            border: 1px solid transparent !important;
            border-bottom: none !important;
            border-radius: 10px 10px 4px 4px !important;
            padding: 10px 20px !important;
            min-width: max-content !important;
            white-space: nowrap !important;
            overflow: visible !important;
            text-overflow: unset !important;
            display: inline-flex !important;
            align-items: center !important;
            height: auto !important;
            margin: 4px 2px 0 2px !important;
            transition: all 0.2s ease !important;
            position: relative !important;
            letter-spacing: 0.01em !important;
        }

        /* Hover: lift subtil + il·luminació */
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"]:hover {
            color: #e2e8f0 !important;
            background: rgba(59, 130, 246, 0.08) !important;
            transform: translateY(-1px) !important;
        }

        /* Tab PRINCIPAL activa — gradient pill amb glow */
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"][aria-selected="true"] {
            color: #ffffff !important;
            background: linear-gradient(135deg,
                rgba(59, 130, 246, 0.22) 0%,
                rgba(139, 92, 246, 0.18) 100%) !important;
            border: 1px solid rgba(59, 130, 246, 0.45) !important;
            border-bottom: none !important;
            box-shadow: 0 2px 12px rgba(59, 130, 246, 0.25),
                        inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
            transform: translateY(0) !important;
        }

        /* Text dins del botó de tab */
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"] p,
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"] span,
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"] div {
            color: inherit !important;
            font-size: inherit !important;
            font-weight: inherit !important;
            overflow: visible !important;
            white-space: nowrap !important;
        }

        /* Contingut de tabs principals */
        div[data-testid="stTabs"] > div[data-testid="stTabsContent"] {
            background: var(--bg-page);
            padding: 28px 8px 24px 8px;
        }

        /* ═══════════════════════════════════════════════════════
           SUB-TABS (nivell 2: dins d'una tab principal)
           ═══════════════════════════════════════════════════════ */
        div[data-testid="stTabsContent"] div[data-testid="stTabs"] > div[role="tablist"] {
            position: static !important;
            background: linear-gradient(180deg, var(--surface-1) 0%, var(--surface-2) 100%) !important;
            border-radius: 12px 12px 0 0 !important;
            border: 1px solid var(--border-1) !important;
            border-bottom: 2px solid var(--accent-blue) !important;
            box-shadow: 0 1px 0 rgba(59, 130, 246, 0.08) !important;
            padding: 6px 8px 0 8px !important;
            gap: 2px !important;
            display: flex !important;
            min-height: auto !important;
        }
        div[data-testid="stTabsContent"] div[data-testid="stTabs"] > div[role="tablist"]::after {
            display: none !important;
        }

        div[data-testid="stTabsContent"] div[data-testid="stTabs"]
            > div[role="tablist"] button[role="tab"] {
            font-family: 'DM Sans', sans-serif !important;
            font-size: 0.82rem !important;
            font-weight: 600 !important;
            padding: 9px 16px !important;
            color: var(--text-muted) !important;
            background: transparent !important;
            border: 1px solid transparent !important;
            border-bottom: none !important;
            border-radius: 9px 9px 0 0 !important;
            margin: 0 1px !important;
            transition: all 0.18s ease !important;
        }

        div[data-testid="stTabsContent"] div[data-testid="stTabs"]
            > div[role="tablist"] button[role="tab"]:hover {
            color: var(--accent-blue-l) !important;
            background: rgba(59, 130, 246, 0.08) !important;
        }

        /* Sub-tab activa */
        div[data-testid="stTabsContent"] div[data-testid="stTabs"]
            > div[role="tablist"] button[role="tab"][aria-selected="true"] {
            color: var(--accent-blue-l) !important;
            background: var(--surface-1) !important;
            border: 1px solid var(--border-1) !important;
            border-bottom: 2px solid var(--surface-1) !important;
            box-shadow: 0 -2px 8px rgba(59, 130, 246, 0.15) !important;
            margin-bottom: -2px !important;
            position: relative !important;
            z-index: 2 !important;
        }

        div[data-testid="stTabsContent"] div[data-testid="stTabs"]
            > div[data-testid="stTabsContent"] {
            background: var(--surface-1);
            border: 1px solid var(--border-1);
            border-top: none;
            border-radius: 0 0 12px 12px;
            padding: 22px 20px 18px 20px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
        }

        /* ── Targetes de secció ── */
        .section-card {
            background: var(--surface-1);
            border: 1px solid var(--border-1);
            border-radius: 14px;
            padding: 0 0 4px 0;
            margin-bottom: 22px;
            box-shadow: 0 2px 14px rgba(0, 0, 0, 0.35),
                        0 1px 3px rgba(0, 0, 0, 0.25);
            overflow: hidden;
            transition: box-shadow 0.2s ease;
        }

        .section-card:hover {
            box-shadow: 0 4px 20px rgba(59, 130, 246, 0.15),
                        0 2px 6px rgba(0, 0, 0, 0.3);
        }

        .section-card-header {
            background: linear-gradient(90deg, var(--surface-2) 0%, var(--surface-1) 60%, rgba(59,130,246,.08) 100%);
            border-bottom: 1px solid var(--border-1);
            padding: 14px 20px 12px 20px;
            position: relative;
        }
        .section-card-header::before {
            content: '';
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: linear-gradient(180deg, var(--accent-blue) 0%, var(--accent-purple) 100%);
        }

        .section-card-title {
            font-size: 1rem;
            font-weight: 700;
            color: var(--text-primary);
            margin: 0 0 2px 0;
            letter-spacing: -0.01em;
        }

        .section-card-subtitle {
            font-size: 0.82rem;
            color: var(--text-muted);
            margin: 0;
            font-weight: 400;
        }

        .section-card-body {
            padding: 12px 18px 10px 18px;
        }

        /* ── Introducció subtab ── */
        .subtab-intro {
            font-size: 0.88rem;
            color: var(--text-secondary);
            background: var(--surface-2);
            border-left: 3px solid var(--accent-blue);
            border-radius: 0 6px 6px 0;
            padding: 8px 14px;
            margin-bottom: 18px;
            font-weight: 400;
        }

        /* ── Taula HTML personalitzada ── */
        .custom-table-wrapper {
            overflow-x: auto;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid var(--border-1);
            max-height: 500px;
        }

        .custom-table-wrapper.tall  { max-height: 680px; }
        .custom-table-wrapper.short { max-height: 280px; }

        .custom-table {
            width: 100%;
            border-collapse: collapse;
            font-family: 'DM Sans', sans-serif;
            font-size: 0.875rem;
        }

        .custom-table thead {
            position: sticky;
            top: 0;
            z-index: 2;
        }

        .custom-table thead th {
            background: #0a0a0a;
            color: var(--text-primary);
            font-weight: 600;
            font-size: 0.78rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            padding: 11px 14px;
            text-align: left;
            white-space: nowrap;
            border-right: 1px solid var(--border-2);
        }

        .custom-table thead th:last-child {
            border-right: none;
        }

        .custom-table tbody tr {
            transition: background 0.12s;
        }

        .custom-table tbody tr:nth-child(even) {
            background: var(--surface-2);
        }

        .custom-table tbody tr:nth-child(odd) {
            background: var(--surface-1);
        }

        .custom-table tbody tr:hover {
            background: rgba(59, 130, 246, 0.1) !important;
        }

        .custom-table tbody td {
            padding: 9px 14px;
            border-bottom: 1px solid var(--border-1);
            border-right: 1px solid var(--border-1);
            color: var(--text-primary);
            white-space: nowrap;
            font-size: 0.875rem;
        }

        .custom-table tbody td:last-child {
            border-right: none;
        }

        /* Primera columna (Ticker) destacada */
        .custom-table tbody td:first-child {
            font-family: 'DM Mono', monospace;
            font-weight: 500;
            font-size: 0.82rem;
            color: #1d4ed8;
            background: inherit;
        }

        /* Cel·les numèriques */
        .custom-table tbody td.num {
            text-align: right;
            font-family: 'DM Mono', monospace;
            font-size: 0.82rem;
            color: #374151;
        }

        /* Buit / NA */
        .custom-table tbody td.na-cell {
            color: #cbd5e1;
            text-align: center;
        }

        /* ── Comptador de files ── */
        .row-count-badge {
            display: inline-block;
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            color: #1d4ed8;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 2px 9px;
            border-radius: 20px;
            margin-left: 8px;
            vertical-align: middle;
        }

        /* ═══════════════════════════════════════════════════════
           MODE IMPRESSIÓ — generar PDF des del navegador (Ctrl+P)
           Optimitzat perquè la sortida no perdi el format del bot:
             • amaga la sidebar i la barra de Streamlit
             • elimina ombres i animacions (millor per PDF)
             • força colors clars de fons per estalviar tinta
             • força salts de pàgina entre seccions principals
             • mostra URLs de manera neta
           Ús: l'usuari prem Ctrl+P (o el botó "Imprimir / desar com a
           PDF" de la barra superior) i el navegador desa la pestanya
           sencera com a PDF, amb el format mantingut.
           ═══════════════════════════════════════════════════════ */
        @media print {
            /* Amaguem chrome de Streamlit que no aporta res al PDF */
            section[data-testid="stSidebar"],
            header[data-testid="stHeader"],
            div[data-testid="stToolbar"],
            footer,
            .stDeployButton,
            #MainMenu,
            button[kind="header"] {
                display: none !important;
            }

            /* Ampliem la zona de contingut a tot l'ample del paper */
            section.main,
            div[data-testid="stAppViewContainer"],
            div[data-testid="block-container"] {
                max-width: 100% !important;
                padding: 0 !important;
                margin: 0 !important;
            }

            /* Per fer el PDF més imprimible: fons clars, lletra negra
               als textos generals (els colors dels números els
               mantenim perquè aporten significat). */
            body, .main {
                background: #ffffff !important;
                color: #000000 !important;
            }

            /* Targetes i taules: caixes amb borders però sense fons fosc.
               L'usuari pot triar "imprimir colors de fons" al diàleg
               d'impressió si vol mantenir el disseny fosc. */
            div[style*="background:#111111"],
            div[style*="background:#0a0a0a"],
            div[style*="background:#0f172a"] {
                background: #f8fafc !important;
                color: #000000 !important;
                border: 1px solid #cbd5e1 !important;
                box-shadow: none !important;
            }

            /* Evitem que les taules es parteixin al mig entre pàgines */
            table {
                page-break-inside: avoid !important;
            }

            /* Els gràfics interactius (iframes injectats per
               components.html) també han d'imprimir-se bé */
            iframe {
                page-break-inside: avoid !important;
                max-width: 100% !important;
            }

            /* Botons no s'imprimeixen */
            .stButton, .stDownloadButton {
                display: none !important;
            }

            /* Tabs de Streamlit: només mostrem el contingut actiu;
               la barra de tabs s'amaga */
            div[data-baseweb="tab-list"] {
                display: none !important;
            }

            /* Tipografia més petita per encabir més per pàgina */
            body { font-size: 10pt; }
            h1 { font-size: 16pt; }
            h2 { font-size: 14pt; }
            h3 { font-size: 12pt; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# HELPERS DE RENDERITZAT
# ============================================================
