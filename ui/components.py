"""
Components UI compartits: render_table, render_page_header, subtab_intro,
_metrics_html (KPIs B&H), _strategy_summary_html (resum de l'estratègia).
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def _is_numeric_col(series: pd.Series) -> bool:
    try:
        pd.to_numeric(series.dropna().head(20))
        return True
    except (ValueError, TypeError):
        return False

def render_page_header(title: str, subtitle: str) -> None:
    # Botó "Imprimir / desar PDF" al header de cada pàgina. Usa
    # window.print() (API nadiva del navegador) que respecta el CSS
    # @media print definit a styles.py. L'usuari prem el botó, surt
    # el diàleg d'impressió del navegador i pot triar "Desar com a PDF"
    # com a destí. Funciona offline; no cal cap llibreria externa.
    st.markdown(
        f"""
        <div class="page-header">
            <div class="page-header-badge">📊 TFG · Anàlisi de Cartera</div>
            <div class="page-header-title">{title}</div>
            <div class="page-header-subtitle">{subtitle}</div>
            <button onclick="window.print()" class="print-pdf-btn"
                    title="Imprimeix aquesta pestanya o desa-la com a PDF
(Ctrl+P · al diàleg, tria 'Desar com a PDF' com a destí)">
                🖨️&nbsp;Desar com a PDF
            </button>
        </div>
        <style>
        .page-header {{ position: relative; }}
        .print-pdf-btn {{
            position: absolute;
            top: 16px; right: 16px;
            background: #1e293b;
            color: #f1f5f9;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 8px 14px;
            font-size: .82rem;
            font-weight: 600;
            cursor: pointer;
            transition: all .15s ease;
            font-family: inherit;
        }}
        .print-pdf-btn:hover {{
            background: #334155;
            border-color: #60a5fa;
        }}
        /* No s'imprimeix dins del PDF */
        @media print {{ .print-pdf-btn {{ display: none !important; }} }}
        </style>
        """,
        unsafe_allow_html=True,
    )

# Alçades per classe: (alçada iframe total, alçada màx. del cos de la taula)
_HEIGHT_MAP = {"tall": (860, 600), "short": (460, 260), "": (700, 460)}

def render_table(
    title: str,
    df: pd.DataFrame,
    subtitle: str | None = None,
    height_class: str = "",
) -> None:
    """
    Taula interactiva amb:
      - Botons per seleccionar/deseleccionar columnes
      - Cerca en temps real
      - Ordenació per columna (clic a la capçalera)
      - Comptador de files visibles
    """

    iframe_h, body_h = _HEIGHT_MAP.get(height_class, (700, 460))
    n_total   = len(df)
    subtitle_h = f'<p class="card-sub">{subtitle}</p>' if subtitle else ""

    numeric_cols = [c for c in df.columns if _is_numeric_col(df[c])]

    # Serialitzem les dades com a llista de dicts (valors string nets)
    def clean(v):
        if pd.isna(v):
            return None
        s = str(v).strip()
        return None if s in {"", "nan", "None", "<NA>"} else s

    rows_data = [[clean(row[c]) for c in df.columns] for _, row in df.iterrows()]
    cols_data  = list(df.columns)

    rows_json   = json.dumps(rows_data,  ensure_ascii=False)
    cols_json   = json.dumps(cols_data,  ensure_ascii=False)
    numeric_json = json.dumps(numeric_cols, ensure_ascii=False)

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,600;0,700;1,400&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin:0; padding:0; }}
  body {{ font-family:'DM Sans',sans-serif; background:transparent; color:#1e293b; }}

  /* ── Card shell ── */
  .card {{
    border:1px solid #e2e8f0; border-radius:14px; overflow:hidden;
    box-shadow:0 3px 12px rgba(15,23,42,.07);
    display:flex; flex-direction:column;
    height:{iframe_h - 8}px;
  }}

  /* ── Card header ── */
  .card-head {{
    background:linear-gradient(100deg,#f8fafc 0%,#eef2ff 100%);
    border-bottom:1px solid #e2e8f0;
    padding:13px 18px 11px;
    flex-shrink:0;
  }}
  .head-row1 {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .card-title {{ font-size:.97rem; font-weight:700; color:#0f172a; letter-spacing:-.015em; }}
  .badge {{
    background:#eff6ff; border:1px solid #bfdbfe; color:#1d4ed8;
    font-size:.7rem; font-weight:700; padding:2px 10px; border-radius:20px;
    letter-spacing:.03em;
  }}
  .vis-badge {{
    background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d;
    font-size:.7rem; font-weight:600; padding:2px 10px; border-radius:20px;
    margin-left:auto;
  }}
  .card-sub {{ font-size:.82rem; color:#64748b; margin-top:4px; }}

  /* ── Toolbar ── */
  .toolbar {{
    background:#f8fafc; border-bottom:1px solid #e8eef5;
    padding:10px 18px 10px; flex-shrink:0;
  }}
  .toolbar-top {{ display:flex; align-items:center; gap:10px; margin-bottom:8px; }}

  .search-wrap {{
    position:relative; flex:1; max-width:320px;
  }}
  .search-wrap svg {{
    position:absolute; left:10px; top:50%; transform:translateY(-50%);
    width:14px; height:14px; stroke:#94a3b8; fill:none; pointer-events:none;
  }}
  .search {{
    width:100%; padding:7px 10px 7px 32px;
    border:1px solid #cbd5e1; border-radius:8px;
    font-family:'DM Sans',sans-serif; font-size:.83rem; color:#1e293b;
    background:#fff; outline:none; transition:border .15s,box-shadow .15s;
  }}
  .search:focus {{ border-color:#3b82f6; box-shadow:0 0 0 3px rgba(59,130,246,.12); }}
  .search::placeholder {{ color:#94a3b8; }}

  .ctrl-btn {{
    font-family:'DM Sans',sans-serif; font-size:.76rem; font-weight:600;
    padding:5px 12px; border-radius:7px; border:1px solid #cbd5e1;
    background:#fff; color:#475569; cursor:pointer;
    transition:all .14s; white-space:nowrap;
  }}
  .ctrl-btn:hover {{ background:#f1f5f9; border-color:#94a3b8; color:#0f172a; }}
  .ctrl-btn.reset {{
    border-color:#fca5a5; background:#fff7f7; color:#dc2626;
  }}
  .ctrl-btn.reset:hover {{ background:#fee2e2; }}

  .row-count {{
    font-size:.76rem; color:#64748b; margin-left:auto; white-space:nowrap;
  }}
  .row-count strong {{ color:#0f172a; }}

  /* ── Column pills ── */
  .col-pills {{ display:flex; flex-wrap:wrap; gap:5px; }}
  .pill {{
    font-family:'DM Sans',sans-serif; font-size:.73rem; font-weight:600;
    padding:4px 11px; border-radius:20px; cursor:pointer;
    border:1px solid #cbd5e1; background:#fff; color:#475569;
    transition:all .14s; user-select:none; white-space:nowrap;
  }}
  .pill.on {{
    background:#1d4ed8; border-color:#1d4ed8; color:#fff;
    box-shadow:0 1px 4px rgba(29,78,216,.25);
  }}
  .pill:hover {{ transform:translateY(-1px); box-shadow:0 2px 6px rgba(0,0,0,.1); }}

  /* ── Table body ── */
  .card-body {{
    overflow-x:auto; overflow-y:auto;
    flex:1 1 0%;
    background:#fff;
  }}

  table {{ width:100%; border-collapse:collapse; font-size:.875rem; }}
  thead {{ position:sticky; top:0; z-index:2; }}
  th {{
    background:#1e293b; color:#e2e8f0;
    font-weight:600; font-size:.72rem; letter-spacing:.05em; text-transform:uppercase;
    padding:11px 14px; text-align:left; white-space:nowrap;
    border-right:1px solid #334155;
    cursor:pointer; user-select:none; transition:background .13s;
  }}
  th:hover {{ background:#273549; }}
  th.sorted-asc::after  {{ content:' ↑'; color:#60a5fa; }}
  th.sorted-desc::after {{ content:' ↓'; color:#60a5fa; }}
  th:last-child {{ border-right:none; }}

  tbody tr:nth-child(even) {{ background:#f8fafc; }}
  tbody tr:nth-child(odd)  {{ background:#fff; }}
  tbody tr:hover           {{ background:#eff6ff !important; }}
  tbody tr.hidden          {{ display:none; }}

  td {{
    padding:9px 14px; border-bottom:1px solid #eef2f7;
    border-right:1px solid #f1f5f9; color:#1e293b; white-space:nowrap;
  }}
  td:last-child {{ border-right:none; }}
  td:first-child {{
    font-family:'DM Mono',monospace; font-weight:500;
    font-size:.82rem; color:#1d4ed8;
  }}
  td.num  {{ text-align:center; font-family:'DM Mono',monospace; font-size:.82rem; color:#374151; }}
  td.na   {{ color:#cbd5e1; text-align:center; font-size:.8rem; }}
  td.hl   {{ background:#fef9c3 !important; }}

  /* ── Empty state ── */
  .empty-state {{
    text-align:center; padding:48px 0; color:#94a3b8; font-size:.88rem;
  }}
  .empty-state svg {{ width:36px; height:36px; stroke:#cbd5e1; fill:none; margin-bottom:10px; }}
</style>
</head>
<body>
<div class="card">

  <!-- HEADER -->
  <div class="card-head">
    <div class="head-row1">
      <span class="card-title">{title}</span>
      <span class="badge" id="totalBadge">{n_total} files</span>
      <span class="vis-badge" id="visBadge"></span>
    </div>
    {subtitle_h}
  </div>

  <!-- TOOLBAR -->
  <div class="toolbar">
    <div class="toolbar-top">
      <div class="search-wrap">
        <svg viewBox="0 0 24 24" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input class="search" id="searchBox" placeholder="Cerca a totes les columnes…">
      </div>
      <button class="ctrl-btn" onclick="selectAll()">✓ Totes</button>
      <button class="ctrl-btn" onclick="selectNone()">✕ Cap</button>
      <button class="ctrl-btn reset" onclick="resetTable()">↺ Reset</button>
      <span class="row-count" id="rowCount"></span>
    </div>
    <div class="col-pills" id="pillContainer"></div>
  </div>

  <!-- TABLE -->
  <div class="card-body">
    <table id="dataTable">
      <thead><tr id="headerRow"></tr></thead>
      <tbody id="tableBody"></tbody>
    </table>
    <div class="empty-state" id="emptyState" style="display:none">
      <svg viewBox="0 0 24 24" stroke-width="1.5">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <br>Sense resultats per a la cerca actual
    </div>
  </div>

</div>

<script>
const COLS     = {cols_json};
const ROWS     = {rows_json};
const NUM_COLS = new Set({numeric_json});

let sortCol   = -1;
let sortAsc   = true;
let visibleCols = new Array(COLS.length).fill(true);
let currentRows = [...ROWS];

// ── Build header ──────────────────────────────────────
function buildHeader() {{
  const tr = document.getElementById('headerRow');
  tr.innerHTML = '';
  COLS.forEach((col, i) => {{
    if (!visibleCols[i]) return;
    const th = document.createElement('th');
    th.textContent = col;
    th.dataset.col = i;
    if (NUM_COLS.has(col)) th.style.textAlign = 'center';
    if (sortCol === i) th.className = sortAsc ? 'sorted-asc' : 'sorted-desc';
    th.onclick = () => sortBy(i);
    tr.appendChild(th);
  }});
}}

// ── Build pills ───────────────────────────────────────
function buildPills() {{
  const container = document.getElementById('pillContainer');
  container.innerHTML = '';
  COLS.forEach((col, i) => {{
    const pill = document.createElement('button');
    pill.className = 'pill' + (visibleCols[i] ? ' on' : '');
    pill.textContent = col;
    pill.onclick = () => toggleCol(i);
    container.appendChild(pill);
  }});
}}

// ── Render rows ───────────────────────────────────────
function renderRows() {{
  const tbody    = document.getElementById('tableBody');
  const query    = document.getElementById('searchBox').value.toLowerCase().trim();
  const fragment = document.createDocumentFragment();
  let   shown    = 0;

  currentRows.forEach(row => {{
    // Filter by search
    const match = !query || row.some(v => v && v.toLowerCase().includes(query));
    if (!match) return;
    shown++;

    const tr = document.createElement('tr');
    COLS.forEach((col, i) => {{
      if (!visibleCols[i]) return;
      const td  = document.createElement('td');
      const val = row[i];
      if (val === null || val === undefined) {{
        td.className = 'na'; td.textContent = '—';
      }} else {{
        td.textContent = val;
        if (NUM_COLS.has(col)) td.className = 'num';
        // Highlight search matches
        if (query && val.toLowerCase().includes(query)) td.classList.add('hl');
      }}
      tr.appendChild(td);
    }});
    fragment.appendChild(tr);
  }});

  tbody.innerHTML = '';
  tbody.appendChild(fragment);

  // Empty state
  document.getElementById('emptyState').style.display = shown === 0 ? 'block' : 'none';
  document.getElementById('dataTable').style.display  = shown === 0 ? 'none'  : 'table';

  // Counters
  const total = ROWS.length;
  document.getElementById('rowCount').innerHTML =
    `Mostrant <strong>${{shown}}</strong> de <strong>${{total}}</strong> files`;

  const visCols = visibleCols.filter(Boolean).length;
  document.getElementById('visBadge').textContent = `${{visCols}} col·lumnes`;
}}

// ── Sort ──────────────────────────────────────────────
function sortBy(colIdx) {{
  if (sortCol === colIdx) {{ sortAsc = !sortAsc; }}
  else {{ sortCol = colIdx; sortAsc = true; }}

  const isNum = NUM_COLS.has(COLS[colIdx]);
  currentRows.sort((a, b) => {{
    const av = a[colIdx], bv = b[colIdx];
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    let cmp;
    if (isNum) {{
      cmp = parseFloat(av.replace(',','.')) - parseFloat(bv.replace(',','.'));
    }} else {{
      cmp = av.localeCompare(bv, 'ca', {{sensitivity:'base'}});
    }}
    return sortAsc ? cmp : -cmp;
  }});
  buildHeader();
  renderRows();
}}

// ── Column toggles ────────────────────────────────────
function toggleCol(i) {{
  // Always keep at least 1 column visible
  const nVisible = visibleCols.filter(Boolean).length;
  if (visibleCols[i] && nVisible <= 1) return;
  visibleCols[i] = !visibleCols[i];
  buildPills(); buildHeader(); renderRows();
}}

function selectAll()  {{ visibleCols = new Array(COLS.length).fill(true);  buildPills(); buildHeader(); renderRows(); }}
function selectNone() {{
  // Keep first col always on
  visibleCols = new Array(COLS.length).fill(false);
  visibleCols[0] = true;
  buildPills(); buildHeader(); renderRows();
}}

function resetTable() {{
  visibleCols = new Array(COLS.length).fill(true);
  sortCol = -1; sortAsc = true;
  currentRows = [...ROWS];
  document.getElementById('searchBox').value = '';
  buildPills(); buildHeader(); renderRows();
}}

// ── Search ────────────────────────────────────────────
document.getElementById('searchBox').addEventListener('input', renderRows);

// ── Init ──────────────────────────────────────────────
buildPills();
buildHeader();
renderRows();
</script>
</body>
</html>"""

    components.html(full_html, height=iframe_h, scrolling=False)
def subtab_intro(text: str) -> None:
    st.markdown(f'<div class="subtab-intro">{text}</div>', unsafe_allow_html=True)
def _strategy_summary_html(result: dict, ticker: str, date_from: str, date_to: str) -> str:
    trades = result["trades"]
    strat_total = result["strat_total"]
    bh_return = result["bh_return"]
    n_trades = result["n_trades"]
    win_rate = result["win_rate"]
    max_dd = result["max_dd"]
    outperforms = strat_total > bh_return

    strat_col = "#16a34a" if strat_total >= 0 else "#dc2626"
    bh_col = "#16a34a" if bh_return >= 0 else "#dc2626"
    vs_col = "#16a34a" if outperforms else "#dc2626"
    vs_text = f"{strat_total - bh_return:+.2f}% vs B&H"

    def kpi(label, value, color="#f1f5f9", sub=None):
        sub_html = f'<div style="font-size:.7rem;color:#94a3b8;margin-top:3px;">{sub}</div>' if sub else ""
        return (
            f'<div style="flex:1;min-width:150px;background:#111111;border:1px solid #2a2a2a;'
            f'border-radius:12px;padding:14px 16px;">'
            f'<div style="font-size:.68rem;color:#94a3b8;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:6px;">{label}</div>'
            f'<div style="font-family:\'DM Mono\',monospace;font-size:1.05rem;font-weight:700;color:{color};">{value}</div>'
            f'{sub_html}</div>'
        )

    kpis = "".join([
        kpi("Estratègia", f"{strat_total:+.2f}%", strat_col),
        kpi("Buy & Hold", f"{bh_return:+.2f}%", bh_col),
        kpi("Diferència", vs_text, vs_col, "Estratègia vs passiva"),
        kpi("Operacions", str(n_trades)),
        kpi("Taxa d'encert", f"{win_rate:.1f}%", "#16a34a" if win_rate >= 50 else "#dc2626"),
        kpi("Max Drawdown", f"{max_dd:.2f}%", "#dc2626"),
        kpi(
            "Comissions totals",
            f"{result.get('total_fees', 0.0):,.2f}€",
            "#f59e0b",
            f"{result.get('total_fees_pct', 0.0):.2f}% del capital inicial",
        ),
    ])

    if not trades:
        trades_html = '<p style="color:#94a3b8;padding:16px;font-size:.85rem;">Cap operació en el període seleccionat.</p>'
    else:
        rows = ""
        for i, t in enumerate(trades, 1):
            ret = float(t["Retorn (%)"])
            pnl = float(t["Guany/Perdua"])
            fees_t = float(t.get("Fees totals",
                                 t.get("Fees compra", 0.0) + t.get("Fees venda", 0.0)))
            ret_col = "#16a34a" if ret > 0 else ("#dc2626" if ret < 0 else "#64748b")
            pnl_col = "#16a34a" if pnl > 0 else ("#dc2626" if pnl < 0 else "#64748b")
            rows += (
                f'<tr style="background:{"#f8fafc" if i%2==0 else "#fff"};">'
                f'<td style="padding:8px;">{i}</td>'
                f'<td style="padding:8px;font-family:monospace;">{t["Entrada"]}</td>'
                f'<td style="padding:8px;font-family:monospace;">{t["Preu entrada"]}</td>'
                f'<td style="padding:8px;font-family:monospace;">{t["DSVWAP entrada"]}</td>'
                f'<td style="padding:8px;font-family:monospace;text-align:center;font-weight:600;">{t.get("Accions", 0)}</td>'
                f'<td style="padding:8px;font-family:monospace;text-align:right;">{t.get("€ Invertits", 0):,.2f}€</td>'
                f'<td style="padding:8px;font-family:monospace;">{t["Sortida"]}</td>'
                f'<td style="padding:8px;font-family:monospace;">{t["Preu sortida"]}</td>'
                f'<td style="padding:8px;font-family:monospace;">{t["DSVWAP sortida"]}</td>'
                f'<td style="padding:8px;font-family:monospace;color:#b45309;text-align:right;">{fees_t:,.2f}€</td>'
                f'<td style="padding:8px;font-family:monospace;color:{pnl_col};font-weight:700;">{pnl:+.2f}€</td>'
                f'<td style="padding:8px;font-family:monospace;color:{ret_col};font-weight:700;text-align:right;">{ret:+.2f}%</td>'
                f'<td style="padding:8px;text-align:center;color:#64748b;">{t["Dies"]}</td>'
                f'</tr>'
            )
        # Fila de TOTALS: comissions acumulades de tot el període.
        tot_fees = float(result.get("total_fees", 0.0))
        tot_pnl = sum(float(t["Guany/Perdua"]) for t in trades)
        tot_pnl_col = "#16a34a" if tot_pnl > 0 else ("#dc2626" if tot_pnl < 0 else "#64748b")
        totals_row = (
            '<tr style="background:#1e293b;color:#e2e8f0;font-weight:700;">'
            '<td colspan="9" style="padding:9px 8px;text-align:right;'
            'text-transform:uppercase;font-size:.72rem;letter-spacing:.04em;">'
            'Totals del període</td>'
            f'<td style="padding:9px 8px;font-family:monospace;color:#fbbf24;text-align:right;">'
            f'{tot_fees:,.2f}€</td>'
            f'<td style="padding:9px 8px;font-family:monospace;color:{tot_pnl_col};">'
            f'{tot_pnl:+.2f}€</td>'
            '<td colspan="2"></td>'
            '</tr>'
        )
        trades_html = f"""
        <div style="overflow-x:auto;max-height:420px;overflow-y:auto;">
        <table style="width:100%;border-collapse:collapse;white-space:nowrap;font-size:.84rem;">
          <thead style="position:sticky;top:0;z-index:2;">
            <tr style="background:#1e293b;color:#e2e8f0;font-size:.68rem;text-transform:uppercase;letter-spacing:.04em;">
              <th style="padding:9px 8px;">#</th>
              <th style="padding:9px 8px;">Entrada</th>
              <th style="padding:9px 8px;">Preu</th>
              <th style="padding:9px 8px;">DSVWAP</th>
              <th style="padding:9px 8px;text-align:center;">Accions</th>
              <th style="padding:9px 8px;text-align:right;">€ Invertits</th>
              <th style="padding:9px 8px;">Sortida</th>
              <th style="padding:9px 8px;">Preu</th>
              <th style="padding:9px 8px;">DSVWAP</th>
              <th style="padding:9px 8px;text-align:right;">Comissions</th>
              <th style="padding:9px 8px;">P/L €</th>
              <th style="padding:9px 8px;text-align:right;">Retorn</th>
              <th style="padding:9px 8px;text-align:center;">Dies</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
          <tfoot style="position:sticky;bottom:0;z-index:2;">{totals_row}</tfoot>
        </table></div>"""

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">'
        '<style>*{box-sizing:border-box;margin:0;padding:0;}body{font-family:DM Sans,sans-serif;background:#f8fafc;padding:2px;}</style>'
        '</head><body>'
        f'''
        <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;
                    box-shadow:0 3px 12px rgba(15,23,42,.07);margin-bottom:20px;">
          <div style="background:linear-gradient(90deg,#0f172a,#1e3a5f);padding:14px 20px;
                      display:flex;align-items:center;gap:10px;">
            <span style="font-size:1rem;">⚡</span>
            <span style="font-size:.95rem;font-weight:700;color:#fff;">
              Estratègia Reversal + DSVWAP ({ticker})
            </span>
            <span style="margin-left:auto;font-size:.75rem;color:#94a3b8;font-family:monospace;">
              {date_from} → {date_to}
            </span>
          </div>
          <div style="padding:16px 18px 10px;">
            <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;">{kpis}</div>
            <div style="font-size:.85rem;font-weight:700;color:#0f172a;margin-bottom:8px;">
              📋 Historial d'operacions
              <span style="font-weight:400;font-size:.78rem;color:#64748b;margin-left:6px;">
                * posició tancada al preu final del període
              </span>
            </div>
            {trades_html}
          </div>
        </div>
        '''
        + "</body></html>"
    )


# ─────────────────────────────────────────────────────────────
# MÈTRIQUES B&H
# ─────────────────────────────────────────────────────────────
def _metrics_html(df: pd.DataFrame) -> str:
    """
    KPIs de l'estadística descriptiva del període (només les 5 mètriques;
    el període + capital inicial passen a ser controls interactius separats).
    """
    if df.empty or "Close" not in df.columns:
        return ""
    closes = df["Close"].dropna()
    if len(closes) < 2:
        return ""

    ret_total = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
    daily_ret = closes.pct_change().dropna()
    vol_ann = daily_ret.std() * (252 ** 0.5) * 100 if len(daily_ret) else 0.0
    sharpe = ((daily_ret.mean() * 252) / (daily_ret.std() * (252 ** 0.5))) if len(daily_ret) and daily_ret.std() > 0 else 0.0

    peak = closes.iloc[0]
    max_dd = 0.0
    for v in closes:
        peak = max(peak, v)
        max_dd = min(max_dd, (v - peak) / peak * 100)

    n_years = max((df["Date"].iloc[-1] - df["Date"].iloc[0]).days / 365.25, 0.01)
    cagr = ((closes.iloc[-1] / closes.iloc[0]) ** (1 / n_years) - 1) * 100

    def card(label, value, color="#f1f5f9"):
        return (
            f'<div style="flex:1;min-width:140px;background:#111111;'
            f'border:1px solid #2a2a2a;border-radius:12px;padding:14px 16px;">'
            f'<div style="font-size:.68rem;color:#94a3b8;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:6px;">{label}</div>'
            f'<div style="font-family:\'DM Mono\',monospace;font-size:1.1rem;font-weight:700;color:{color};">{value}</div>'
            f'</div>'
        )

    rt_col = "#16a34a" if ret_total >= 0 else "#dc2626"
    cagr_col = "#16a34a" if cagr >= 0 else "#dc2626"

    cards = "".join([
        card("Retorn total", f"{ret_total:+.2f}%", rt_col),
        card("CAGR", f"{cagr:+.2f}%", cagr_col),
        card("Volatilitat anual", f"{vol_ann:.2f}%"),
        card("Sharpe (anual)", f"{sharpe:.2f}"),
        card("Màx. Drawdown", f"{max_dd:.2f}%", "#dc2626"),
    ])
    return '<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;">' + cards + '</div>'


# ─────────────────────────────────────────────────────────────
# TAB 1 — ACCIÓ INDIVIDUAL
