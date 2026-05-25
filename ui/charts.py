"""
Builders d'HTML per als gràfics interactius (lightweight-charts) i SVG inline.

Inclou:
  • _build_strategy_chart_html      → gràfic estàtic veles + DSVWAP + volum
  • _build_portfolio_timeline_html  → línia temporal d'esdeveniments
  • _build_equity_curve_html        → 3 línies (Estratègia + B&H + MSCI)
  • _build_mini_equity_svg          → SVG inline per a targetes
  • _build_mini_equity_html         → versió HTML/lightweight-charts
  • _build_replay_chart_html        → reproductor animat del backtest
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import DEFAULT_CFG
from core.data_io import _resample_index_to_dates
from core.helpers import _logo_html


def _build_strategy_chart_html(df: pd.DataFrame, ticker: str, company: str, result: dict) -> str:

    needed = {"Open", "High", "Low", "Close", "DSVWAP"}
    if not needed.issubset(df.columns):
        return "<p style='color:#ef4444;padding:20px;'>Falten columnes OHLC/indicadors.</p>"

    plot_df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    dates_js = json.dumps([str(d)[:10] for d in plot_df["Date"]])
    o_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["Open"]])
    h_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["High"]])
    l_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["Low"]])
    c_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["Close"]])
    v_js = json.dumps([None if pd.isna(v) else float(v) for v in plot_df["Volume"]]) if "Volume" in plot_df.columns else "[]"

    dsvwap_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["DSVWAP"]])
    dsvwap_up_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["DSVWAP_Upper"]])
    dsvwap_low_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["DSVWAP_Lower"]])

    # ATR% (14): ATR_rel × 100. Ja calculat al build_strategy_dataset (columna 'ATR_rel').
    # Si per algun motiu no existeix (datasets antics), la sèrie queda buida.
    if "ATR_rel" in plot_df.columns:
        atr_pct_js = json.dumps([
            None if pd.isna(v) else round(float(v) * 100.0, 4)
            for v in plot_df["ATR_rel"]
        ])
    else:
        atr_pct_js = "[]"

    # Punts de reversal bruts (abans de la condició de DSVWAP).
    # Llistes d'índexs on es dispara cada tipus.
    bull_rev_js = "[]"
    bear_rev_js = "[]"
    if "BullishReversal" in plot_df.columns:
        bull_rev_js = json.dumps([
            i for i, v in enumerate(plot_df["BullishReversal"].fillna(False).tolist())
            if v
        ])
    if "BearishReversal" in plot_df.columns:
        bear_rev_js = json.dumps([
            i for i, v in enumerate(plot_df["BearishReversal"].fillna(False).tolist())
            if v
        ])

    eq_js = json.dumps(result["equity"], ensure_ascii=False)
    sig_js = json.dumps(result["signals"], ensure_ascii=False)

    closes = plot_df["Close"].dropna()
    last_px = float(closes.iloc[-1])
    prev_px = float(closes.iloc[-2]) if len(closes) > 1 else last_px
    chg_pct = (last_px / prev_px - 1.0) * 100.0 if prev_px != 0 else 0.0
    chg_sign = "▲" if chg_pct >= 0 else "▼"
    chg_col = "#34d399" if chg_pct >= 0 else "#f87171"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&family=DM+Mono:wght@500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans',sans-serif;background:#0b1120;color:#e2e8f0;}}
.shell{{border-radius:14px;overflow:hidden;border:1px solid #1e293b;box-shadow:0 6px 32px rgba(0,0,0,.55);}}
.topbar{{
  background:linear-gradient(110deg,#0f172a 0%,#1e3a5f 100%);
  padding:14px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;
  border-bottom:1px solid #1e293b;
}}
.tk{{font-family:'DM Mono',monospace;font-size:.76rem;color:#60a5fa;letter-spacing:.12em;text-transform:uppercase;margin-bottom:3px;}}
.nm{{font-size:1.1rem;font-weight:700;color:#f1f5f9;}}
.bh-badge{{background:rgba(52,211,153,.14);border:1px solid rgba(52,211,153,.35);color:#34d399;font-size:.72rem;font-weight:700;padding:4px 12px;border-radius:20px;letter-spacing:.04em;white-space:nowrap;}}
.pbox{{margin-left:auto;text-align:right;}}
.plast{{font-family:'DM Mono',monospace;font-size:1.2rem;font-weight:700;color:{chg_col};}}
.pchg{{font-size:.78rem;font-weight:600;color:{chg_col};margin-top:2px;}}

.view-tabs{{background:#0f172a;display:flex;gap:0;border-bottom:2px solid #1e293b;padding:0 16px;}}
.vt{{font-size:.8rem;font-weight:600;padding:10px 18px;color:#64748b;cursor:pointer;border:none;border-bottom:2px solid transparent;background:none;font-family:'DM Sans',sans-serif;margin-bottom:-2px;transition:all .14s;}}
.vt.on{{color:#60a5fa;border-bottom-color:#3b82f6;}}
.vt:hover{{color:#93c5fd;}}

.toolbar{{background:#0f172a;padding:8px 16px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;border-bottom:1px solid #1e293b;}}
.pb{{font-family:'DM Sans',sans-serif;font-size:.73rem;font-weight:600;padding:5px 12px;border-radius:7px;border:1px solid #334155;background:transparent;color:#94a3b8;cursor:pointer;transition:all .13s;}}
.pb.on,.pb:hover{{background:#1d4ed8;border-color:#1d4ed8;color:#fff;}}
.sep{{width:1px;height:18px;background:#334155;margin:0 3px;flex-shrink:0;}}
.ob{{font-family:'DM Sans',sans-serif;font-size:.7rem;font-weight:600;padding:4px 10px;border-radius:6px;border:1px solid #334155;background:transparent;color:#64748b;cursor:pointer;transition:all .13s;}}
.ob.on{{background:#0c2d5f;border-color:#3b82f6;color:#93c5fd;}}

#cDiv{{background:#0b1120;position:relative;min-height:300px;}}
#vDiv{{background:#0b1120;border-top:1px solid #151f2e;min-height:90px;}}
#aDiv{{background:#0b1120;border-top:1px solid #151f2e;position:relative;min-height:120px;}}
.atr-label{{
  position:absolute;top:6px;left:10px;z-index:5;pointer-events:none;
  font-family:'DM Mono',monospace;font-size:.7rem;color:#ef4444;
  font-weight:600;letter-spacing:.02em;
}}
.atr-label .lbl{{color:#94a3b8;font-weight:500;margin-right:4px;}}
#eDiv{{background:#0b1120;display:none;}}
.legend{{display:flex;gap:14px;align-items:center;font-size:.72rem;color:#94a3b8;padding:7px 16px;background:#0f172a;border-bottom:1px solid #1e293b;}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle;}}

/* ── Tooltip flotant sobre marcadors ── */
.op-tooltip{{
  position:absolute;z-index:50;pointer-events:none;
  background:#fff;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.55);
  padding:0;overflow:hidden;width:280px;
  font-family:'DM Sans',sans-serif;color:#1e293b;
  opacity:0;transform:translateY(4px);transition:opacity .15s,transform .15s;
}}
.op-tooltip.visible{{opacity:1;transform:translateY(0);}}
.op-tooltip .tip-head{{
  padding:8px 12px;color:#fff;font-weight:700;font-size:.78rem;
  display:flex;align-items:center;gap:6px;
}}
.op-tooltip.buy .tip-head{{background:linear-gradient(100deg,#15803d,#22c55e);}}
.op-tooltip.sell .tip-head{{background:linear-gradient(100deg,#991b1b,#ef4444);}}
.op-tooltip .tip-head .date{{margin-left:auto;font-family:'DM Mono',monospace;font-size:.68rem;opacity:.94;font-weight:500;}}
.op-tooltip .tip-body{{padding:8px 12px;}}
.op-tooltip .row{{display:flex;justify-content:space-between;padding:3px 0;font-size:.74rem;border-bottom:1px dashed #e2e8f0;}}
.op-tooltip .row:last-child{{border-bottom:none;}}
.op-tooltip .k{{color:#64748b;font-weight:500;}}
.op-tooltip .v{{font-family:'DM Mono',monospace;font-weight:700;color:#0f172a;font-size:.72rem;}}
.op-tooltip .v.ok{{color:#16a34a;}}
.op-tooltip .v.bad{{color:#dc2626;}}
.op-tooltip .v.warn{{color:#d97706;}}

/* ── Panell fix amb última operació revisada ── */
.pinned-panel{{
  display:none;margin-left:auto;background:#1e293b;border:1px solid #334155;
  border-radius:8px;padding:5px 11px;font-size:.72rem;
  gap:8px;align-items:center;max-width:46%;
}}
.pinned-panel.visible{{display:inline-flex;}}
.pinned-panel .pp-pill{{
  padding:1px 8px;border-radius:10px;font-weight:700;font-size:.62rem;
  letter-spacing:.05em;text-transform:uppercase;
}}
.pinned-panel .pp-pill.buy{{background:rgba(52,211,153,.22);color:#34d399;}}
.pinned-panel .pp-pill.sell{{background:rgba(248,113,113,.22);color:#f87171;}}
.pinned-panel .pp-txt{{color:#cbd5e1;font-family:'DM Mono',monospace;font-size:.7rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.pinned-panel .pp-close{{
  background:none;border:none;color:#64748b;cursor:pointer;font-size:1rem;padding:0 2px;
  margin-left:4px;line-height:1;
}}
.pinned-panel .pp-close:hover{{color:#f87171;}}
</style>
</head>
<body>
<div class="shell">
  <div class="topbar">
    <div><div class="tk">{ticker}</div><div class="nm">{company}</div></div>
    <div class="bh-badge">🧠 Reversal + DSVWAP</div>
    <div class="pbox">
      <div class="plast">{last_px:.2f}</div>
      <div class="pchg">{chg_sign} {abs(chg_pct):.2f}%</div>
    </div>
  </div>

  <div class="view-tabs">
    <button class="vt on" id="vtC" onclick="setView('c')">🕯 Veles japoneses</button>
    <button class="vt" id="vtE" onclick="setView('e')">📈 Corba de capital</button>
  </div>

  <div class="toolbar" id="tlbar">
    <button class="pb on" id="pb1y" onclick="sp(this,365)">1A</button>
    <button class="pb" onclick="sp(this,30)">1M</button>
    <button class="pb" onclick="sp(this,90)">3M</button>
    <button class="pb" onclick="sp(this,180)">6M</button>
    <button class="pb" onclick="sp(this,730)">2A</button>
    <button class="pb" onclick="sp(this,1825)">5A</button>
    <button class="pb" onclick="sp(this,99999)">Tot</button>
    <div class="sep"></div>
    <button class="ob on" id="oVW" onclick="tog('vwap')">DSVWAP</button>
    <button class="ob" id="oBD" onclick="tog('bands')">Bandes</button>
    <button class="ob" id="oRV" onclick="tog('reversals')">Reversals</button>
    <div class="sep"></div>
    <button class="pb" onclick="downloadPng()" title="Descarrega aquest gràfic com a imatge PNG">
      📸 PNG
    </button>
  </div>

  <div class="legend">
    <span><span class="dot" style="background:#3b82f6;"></span>DSVWAP</span>
    <span><span class="dot" style="background:#34d399;"></span>Compra</span>
    <span><span class="dot" style="background:#f87171;"></span>Venda</span>
    <span style="color:#64748b;font-size:.68rem;margin-left:8px;">💡 Passa el ratolí sobre un marcador</span>
    <div class="pinned-panel" id="pinnedPanel">
      <span class="pp-pill" id="ppPill"></span>
      <span class="pp-txt" id="ppText"></span>
      <button class="pp-close" id="ppClose" title="Tancar">×</button>
    </div>
  </div>

  <div id="cDiv">
    <div class="op-tooltip" id="opTooltip">
      <div class="tip-head">
        <span id="tipIcon">🟢</span>
        <span id="tipTitle">COMPRA</span>
        <span class="date" id="tipDate"></span>
      </div>
      <div class="tip-body" id="tipBody"></div>
    </div>
  </div>
  <div id="vDiv"></div>
  <div id="aDiv">
    <div class="atr-label"><span class="lbl">ATR% (14)</span><span id="atrCurVal">—</span></div>
  </div>
  <div id="eDiv"></div>
</div>

<script>
const DATES={dates_js};
const O={o_js}, H={h_js}, L={l_js}, C={c_js}, VOL={v_js};
const DSVWAP={dsvwap_js}, DSVWAP_U={dsvwap_up_js}, DSVWAP_L={dsvwap_low_js};
const ATR_PCT={atr_pct_js};
const EQ={eq_js};
const SIG={sig_js};

// Índexs dels punts de reversal bruts (independents de la condició del DSVWAP)
const BULL_REV_IDX = {bull_rev_js};
const BEAR_REV_IDX = {bear_rev_js};

let ov={{vwap:true,bands:false,reversals:false}};
let curView='c';

const candles=DATES.map((d,i)=>O[i]!==null?{{time:d,open:O[i],high:H[i],low:L[i],close:C[i]}}:null).filter(Boolean);
const vols=DATES.map((d,i)=>VOL[i]!==null?{{time:d,value:VOL[i],color:(C[i]>=O[i])?'rgba(52,211,153,.45)':'rgba(248,113,113,.45)'}}:null).filter(Boolean);
const atrPctData=DATES.map((d,i)=>(ATR_PCT[i]!==null && ATR_PCT[i]!==undefined)?{{time:d,value:ATR_PCT[i]}}:null).filter(Boolean);
const mkLine=(arr,dts)=>arr.map((v,i)=>v!==null?{{time:dts[i],value:v}}:null).filter(Boolean);

const W=()=>document.getElementById('cDiv').offsetWidth||900;
// Alçades fixes per als 3 panells. window.innerHeight dins un iframe pot donar
// valors petits/inesperats; per això usem valors absoluts mínims que garanteixen
// visibilitat a tots els navegadors i layouts.
const cH=Math.max(380, Math.round(window.innerHeight*0.50));
const vH=Math.max(100, Math.round(cH*0.22));
const aH=Math.max(130, Math.round(cH*0.26));  // panell ATR% una mica més gran per visibilitat

const mc=LightweightCharts.createChart(document.getElementById('cDiv'),{{
  width:W(),height:cH,
  layout:{{background:{{color:'#0b1120'}},textColor:'#94a3b8'}},
  grid:{{vertLines:{{color:'#151f2e'}},horzLines:{{color:'#151f2e'}}}},
  crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},
  rightPriceScale:{{borderColor:'#334155'}},
  timeScale:{{borderColor:'#334155',timeVisible:true}},
}});
const vc=LightweightCharts.createChart(document.getElementById('vDiv'),{{
  width:W(),height:vH,
  layout:{{background:{{color:'#0b1120'}},textColor:'#475569'}},
  grid:{{vertLines:{{color:'#151f2e'}},horzLines:{{color:'#151f2e'}}}},
  rightPriceScale:{{borderColor:'#334155',scaleMargins:{{top:.1,bottom:.0}}}},
  timeScale:{{borderColor:'#334155',timeVisible:true,visible:false}},
}});
// Panell ATR% (línia vermella) — sincronitzat amb el principal
const ac=LightweightCharts.createChart(document.getElementById('aDiv'),{{
  width:W(),height:aH,
  layout:{{background:{{color:'#0b1120'}},textColor:'#475569'}},
  grid:{{vertLines:{{color:'#151f2e'}},horzLines:{{color:'#151f2e'}}}},
  rightPriceScale:{{borderColor:'#334155',scaleMargins:{{top:.1,bottom:.05}}}},
  timeScale:{{borderColor:'#334155',timeVisible:true}},
}});

const cs=mc.addCandlestickSeries({{
  upColor:'#34d399',downColor:'#f87171',
  borderUpColor:'#34d399',borderDownColor:'#f87171',
  wickUpColor:'#34d399',wickDownColor:'#f87171',
}});

const ds=mc.addLineSeries({{color:'#3b82f6', lineWidth:2, lastValueVisible:true, priceLineVisible:false}});
const bu=mc.addLineSeries({{color:'rgba(59,130,246,.35)', lineWidth:1, lastValueVisible:false, priceLineVisible:false}});
const bl=mc.addLineSeries({{color:'rgba(59,130,246,.35)', lineWidth:1, lastValueVisible:false, priceLineVisible:false}});
const vs=vc.addHistogramSeries({{priceFormat:{{type:'volume'}}}});

// Sèrie ATR% al panell inferior — línia vermella estil TradingView
const atrSeries=ac.addLineSeries({{
  color:'#ef4444', lineWidth:1.5,
  lastValueVisible:true, priceLineVisible:false,
  crosshairMarkerVisible:false,
  priceFormat:{{type:'price', precision:2, minMove:0.01}},
}});
atrSeries.setData(atrPctData);

// Mostra el valor actual a la llegenda
if (atrPctData.length > 0) {{
  const lastAtr = atrPctData[atrPctData.length - 1].value;
  const el = document.getElementById('atrCurVal');
  if (el) el.textContent = Number(lastAtr).toFixed(2) + '%';
}}

cs.setData(candles);
vs.setData(vols);

function applyMarkers(){{
  const markers = SIG.map(s => {{
    return {{
      time: s.time,
      position: s.type === 'buy' ? 'belowBar' : 'aboveBar',
      color: s.type === 'buy' ? '#34d399' : '#f87171',
      shape: s.type === 'buy' ? 'arrowUp' : 'arrowDown',
      text: s.type === 'buy' ? 'C' : 'V',
      size: 1,
    }}
  }});

  // Afegim punts de reversal bruts si el toggle està actiu.
  // Evitem duplicar punts que ja són compra/venda executada.
  if (ov.reversals) {{
    const execTimes = new Set(SIG.map(s => String(s.time).replace(' *','')));
    BULL_REV_IDX.forEach(i => {{
      const t = DATES[i];
      if (!execTimes.has(t)) {{
        markers.push({{
          time: t,
          position: 'belowBar',
          color: 'rgba(52,211,153,.55)',
          shape: 'circle',
          text: '',
          size: 0,
        }});
      }}
    }});
    BEAR_REV_IDX.forEach(i => {{
      const t = DATES[i];
      if (!execTimes.has(t)) {{
        markers.push({{
          time: t,
          position: 'aboveBar',
          color: 'rgba(248,113,113,.55)',
          shape: 'circle',
          text: '',
          size: 0,
        }});
      }}
    }});
  }}

  markers.sort((a,b)=>a.time < b.time ? -1 : 1);
  cs.setMarkers(markers);
}}

// ── Tooltip + panell fix al passar sobre marcadors ──
const SIG_BY_TIME = {{}};
SIG.forEach(s => {{ SIG_BY_TIME[String(s.time).replace(' *','')] = s; }});
const opTooltip = document.getElementById('opTooltip');
const pinnedPanel = document.getElementById('pinnedPanel');
const ppPill = document.getElementById('ppPill');
const ppText = document.getElementById('ppText');
document.getElementById('ppClose').addEventListener('click', () => {{
  pinnedPanel.classList.remove('visible');
}});

function fmtNum(v, d=2) {{
  if (v === null || v === undefined) return '—';
  return Number(v).toLocaleString('ca-ES', {{minimumFractionDigits:d, maximumFractionDigits:d}});
}}

function buildTooltipBody(s) {{
  const isBuy = s.type === 'buy';
  const rows = [];

  if (isBuy) {{
    // Criteris de compra
    if (s.bull_strength !== null && s.bull_strength !== undefined) {{
      const cls = s.bull_strength >= 1.5 ? 'ok' : (s.bull_strength >= 1.2 ? 'warn' : '');
      rows.push(`<div class="row"><span class="k">✓ Bullish reversal</span><span class="v ${{cls}}">${{s.bull_strength.toFixed(2)}}× llindar</span></div>`);
    }}
    if (s.dsvwap_dist_atr !== null && s.dsvwap_dist_atr !== undefined) {{
      const cls = s.dsvwap_dist_atr >= 1.0 ? 'ok' : (s.dsvwap_dist_atr >= 0.3 ? 'warn' : '');
      rows.push(`<div class="row"><span class="k">✓ Close &gt; DSVWAP</span><span class="v ${{cls}}">+${{fmtNum(s.dsvwap_dist_atr,2)}} ATR</span></div>`);
    }}
    rows.push(`<div class="row"><span class="k">Preu execució</span><span class="v">${{fmtNum(s.close)}}</span></div>`);
    rows.push(`<div class="row"><span class="k">DSVWAP</span><span class="v">${{fmtNum(s.dsvwap)}}</span></div>`);
    if (s.atr_rel_pct !== null && s.atr_rel_pct !== undefined) {{
      rows.push(`<div class="row"><span class="k">ATR/Preu</span><span class="v">${{fmtNum(s.atr_rel_pct,2)}}%</span></div>`);
    }}
    if (s.shares !== undefined) rows.push(`<div class="row"><span class="k">Accions</span><span class="v">${{s.shares}}</span></div>`);
    if (s.invested !== undefined) rows.push(`<div class="row"><span class="k">€ Invertits</span><span class="v">${{fmtNum(s.invested)}}€</span></div>`);
    // Info de confirmació
    if (s.delay_bars !== undefined && s.delay_bars > 0) {{
      rows.push(`<div class="row"><span class="k">Senyal original</span><span class="v">${{s.signal_date}}</span></div>`);
      rows.push(`<div class="row"><span class="k">Retard confirmació</span><span class="v">${{s.delay_bars}} barra${{s.delay_bars > 1 ? 's' : ''}}</span></div>`);
    }}
  }} else {{
    // Criteris de venda
    if (s.bear_strength !== null && s.bear_strength !== undefined) {{
      rows.push(`<div class="row"><span class="k">✓ Bearish reversal</span><span class="v">${{s.bear_strength.toFixed(2)}}× llindar</span></div>`);
    }} else if (s.forced_close) {{
      rows.push(`<div class="row"><span class="k">⚠ Tancament forçat</span><span class="v warn">Final període</span></div>`);
    }}
    if (s.dsvwap_dist_atr !== null && s.dsvwap_dist_atr !== undefined) {{
      rows.push(`<div class="row"><span class="k">✓ Close &lt; DSVWAP</span><span class="v">${{fmtNum(s.dsvwap_dist_atr,2)}} ATR</span></div>`);
    }}
    rows.push(`<div class="row"><span class="k">Preu execució</span><span class="v">${{fmtNum(s.close)}}</span></div>`);
    rows.push(`<div class="row"><span class="k">DSVWAP</span><span class="v">${{fmtNum(s.dsvwap)}}</span></div>`);
    rows.push(`<div class="row"><span class="k">Entrada</span><span class="v">${{s.entry_date}} · ${{fmtNum(s.entry_price)}}</span></div>`);
    rows.push(`<div class="row"><span class="k">Dies mantinguda</span><span class="v">${{s.days || 0}}</span></div>`);
    const pnl = s.pnl ?? 0;
    const ret = s.ret_pct ?? 0;
    const pnlCls = pnl >= 0 ? 'ok' : 'bad';
    rows.push(`<div class="row"><span class="k">P/L</span><span class="v ${{pnlCls}}">${{pnl >= 0 ? '+' : ''}}${{fmtNum(pnl)}}€</span></div>`);
    rows.push(`<div class="row"><span class="k">Retorn</span><span class="v ${{pnlCls}}">${{ret >= 0 ? '+' : ''}}${{fmtNum(ret,2)}}%</span></div>`);
    if (s.delay_bars !== undefined && s.delay_bars > 0) {{
      rows.push(`<div class="row"><span class="k">Retard confirmació</span><span class="v">${{s.delay_bars}} barra${{s.delay_bars > 1 ? 's' : ''}}</span></div>`);
    }}
  }}
  return rows.join('');
}}

function showTooltip(s, x, y) {{
  opTooltip.className = 'op-tooltip ' + s.type + ' visible';
  document.getElementById('tipIcon').textContent = s.type === 'buy' ? '🟢' : '🔴';
  document.getElementById('tipTitle').textContent = s.type === 'buy' ? 'COMPRA' : 'VENDA';
  document.getElementById('tipDate').textContent = String(s.time).replace(' *','');
  document.getElementById('tipBody').innerHTML = buildTooltipBody(s);

  // Posició dinàmica (evita sortir del gràfic)
  const rect = document.getElementById('cDiv').getBoundingClientRect();
  const ttWidth = 280;
  const ttHeight = opTooltip.offsetHeight || 260;
  let leftPx = x + 15;
  if (leftPx + ttWidth > rect.width - 10) leftPx = x - ttWidth - 15;
  if (leftPx < 10) leftPx = 10;
  let topPx = y + 15;
  if (topPx + ttHeight > rect.height - 10) topPx = y - ttHeight - 15;
  if (topPx < 10) topPx = 10;
  opTooltip.style.left = leftPx + 'px';
  opTooltip.style.top = topPx + 'px';
}}

function hideTooltip() {{
  opTooltip.classList.remove('visible');
}}

function pinOperation(s) {{
  pinnedPanel.classList.add('visible');
  ppPill.className = 'pp-pill ' + s.type;
  ppPill.textContent = s.type === 'buy' ? '🟢 COMPRA' : '🔴 VENDA';
  const parts = [String(s.time).replace(' *',''), `Preu ${{fmtNum(s.close)}}`];
  if (s.type === 'buy') {{
    if (s.shares !== undefined) parts.push(`${{s.shares}} acc`);
  }} else {{
    const pnl = s.pnl ?? 0;
    const ret = s.ret_pct ?? 0;
    parts.push(`P/L ${{pnl >= 0 ? '+' : ''}}${{fmtNum(pnl)}}€ (${{ret >= 0 ? '+' : ''}}${{fmtNum(ret,2)}}%)`);
  }}
  ppText.textContent = parts.join(' · ');
}}

mc.subscribeCrosshairMove(param => {{
  if (!param || !param.time || !param.point) {{
    hideTooltip();
    return;
  }}
  const sig = SIG_BY_TIME[String(param.time)];
  if (sig) {{
    showTooltip(sig, param.point.x, param.point.y);
    pinOperation(sig);
  }} else {{
    hideTooltip();
  }}
}});

function updOv(){{
  ds.setData(ov.vwap ? mkLine(DSVWAP,DATES) : []);
  bu.setData(ov.bands ? mkLine(DSVWAP_U,DATES) : []);
  bl.setData(ov.bands ? mkLine(DSVWAP_L,DATES) : []);
  applyMarkers();  // també re-aplica marcadors (inclou punts de reversal si toggle actiu)
}}

applyMarkers();
updOv();

// Sincronització de timescale entre els 3 panells: principal, volum, ATR%
mc.timeScale().subscribeVisibleLogicalRangeChange(r=>{{
  if(r){{
    vc.timeScale().setVisibleLogicalRange(r);
    ac.timeScale().setVisibleLogicalRange(r);
  }}
}});

const ec=LightweightCharts.createChart(document.getElementById('eDiv'),{{
  width:W(),height:cH+vH+1,
  layout:{{background:{{color:'#0b1120'}},textColor:'#94a3b8'}},
  grid:{{vertLines:{{color:'#151f2e'}},horzLines:{{color:'#151f2e'}}}},
  crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},
  rightPriceScale:{{borderColor:'#334155'}},
  timeScale:{{borderColor:'#334155',timeVisible:true}},
}});
const es=ec.addAreaSeries({{
  topColor:'rgba(52,211,153,.22)',
  bottomColor:'rgba(52,211,153,0)',
  lineColor:'#34d399',
  lineWidth:2,
}});
const ref100=ec.addLineSeries({{
  color:'rgba(148,163,184,.3)',
  lineWidth:1,
  lineStyle:3,
  lastValueVisible:false,
  priceLineVisible:false,
}});
es.setData(EQ);
if(EQ.length){{
  ref100.setData([{{time:EQ[0].time,value:{DEFAULT_CFG.capital_inicial}}},{{time:EQ.at(-1).time,value:{DEFAULT_CFG.capital_inicial}}}]);
}}

function setView(v){{
  curView=v;
  document.getElementById('vtC').classList.toggle('on',v==='c');
  document.getElementById('vtE').classList.toggle('on',v==='e');
  document.getElementById('cDiv').style.display=v==='c'?'block':'none';
  document.getElementById('vDiv').style.display=v==='c'?'block':'none';
  document.getElementById('aDiv').style.display=v==='c'?'block':'none';
  document.getElementById('eDiv').style.display=v==='e'?'block':'none';
  if(v==='e') ec.timeScale().fitContent();
}}

function tog(k){{
  ov[k]=!ov[k];
  const ids={{vwap:'oVW',bands:'oBD',reversals:'oRV'}};
  document.getElementById(ids[k]).classList.toggle('on',ov[k]);
  updOv();
}}

function sp(btn,days){{
  document.querySelectorAll('.pb').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  const chart=curView==='c'?mc:ec;
  if(days>=99999){{
    chart.timeScale().fitContent();
    if(curView==='c'){{
      vc.timeScale().fitContent();
      ac.timeScale().fitContent();
    }}
    return;
  }}
  const last=new Date(DATES.at(-1)), from=new Date(last);
  from.setDate(from.getDate()-days);
  const range={{from:from.toISOString().slice(0,10),to:last.toISOString().slice(0,10)}};
  chart.timeScale().setVisibleRange(range);
  if(curView==='c'){{
    vc.timeScale().setVisibleRange(range);
    ac.timeScale().setVisibleRange(range);
  }}
}}

sp(document.getElementById('pb1y'),365);

// ── Descàrrega PNG ────────────────────────────────────────────
// Genera un PNG del gràfic principal de preu (panell mc). Si volguéssim
// exportar els 3 panells (preu + volum + ATR) en una sola imatge,
// caldria compositar tres canvas, cosa més complexa; aquí ens centrem
// en el panell principal, que és el rellevant per al treball.
function downloadPng() {{
  try {{
    const canvas = mc.takeScreenshot();
    canvas.toBlob(function(blob) {{
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const ts = new Date().toISOString().slice(0,10);
      link.href = url;
      link.download = 'grafic_estrategia_' + ts + '.png';
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {{
        URL.revokeObjectURL(url);
        link.remove();
      }}, 100);
    }}, 'image/png');
  }} catch (e) {{
    alert('Error generant el PNG: ' + e.message);
  }}
}}

new ResizeObserver(()=>{{
  const w=W();
  mc.applyOptions({{width:w}});
  vc.applyOptions({{width:w}});
  ac.applyOptions({{width:w}});
  ec.applyOptions({{width:w}});
}}).observe(document.getElementById('cDiv'));
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# REPRODUCTOR DE BACKTEST — HTML
# Gràfic animat amb Play/Pause/Seg-Prev/Slider + popup de criteris


# ─────────────────────────────────────────────────────────────
# LÍNIA TEMPORAL AGREGADA DE CARTERA
# ─────────────────────────────────────────────────────────────
def _build_portfolio_timeline_html(events: list, date_from: str, date_to: str, n_assets: int) -> str:
    """
    Línia temporal cronològica de tots els esdeveniments (compres i vendes)
    de tots els actius d'una cartera.
    `events` = llista de dicts amb: time, ticker, company, type, price, pnl, ret_pct...
    """

    if not events:
        return """<!DOCTYPE html><html><head><meta charset="utf-8">
        <style>body{font-family:sans-serif;background:#f8fafc;padding:30px;color:#64748b;text-align:center;}</style>
        </head><body>Cap operació registrada al període seleccionat.</body></html>"""

    evs_json = json.dumps(events, ensure_ascii=False)
    n_events = len(events)
    n_buys = sum(1 for e in events if e["type"] == "buy")
    n_sells = n_events - n_buys

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans',sans-serif;background:#f8fafc;padding:4px;color:#1e293b;}}

.shell{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;box-shadow:0 3px 12px rgba(15,23,42,.07);}}

.hdr{{
  background:linear-gradient(100deg,#0f172a,#1e3a5f);
  padding:14px 20px;color:#fff;display:flex;align-items:center;gap:12px;flex-wrap:wrap;
}}
.hdr .title{{font-size:1rem;font-weight:700;}}
.hdr .sub{{font-size:.78rem;color:#94a3b8;margin-left:auto;font-family:'DM Mono',monospace;}}

.toolbar{{
  background:#f8fafc;border-bottom:1px solid #e8eef5;
  padding:10px 18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
}}
.stat{{
  display:inline-flex;align-items:center;gap:7px;font-size:.78rem;color:#475569;
  padding:4px 12px;background:#fff;border:1px solid #e2e8f0;border-radius:20px;
}}
.stat strong{{color:#0f172a;font-family:'DM Mono',monospace;}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;}}
.dot.buy{{background:#16a34a;}}
.dot.sell{{background:#dc2626;}}

.filter-group{{margin-left:auto;display:flex;gap:6px;}}
.fbtn{{
  font-size:.73rem;font-weight:600;padding:4px 12px;border-radius:7px;
  border:1px solid #cbd5e1;background:#fff;color:#475569;cursor:pointer;
  transition:all .13s;
}}
.fbtn:hover{{background:#eff6ff;border-color:#3b82f6;}}
.fbtn.on{{background:#1d4ed8;border-color:#1d4ed8;color:#fff;}}

.search{{
  padding:5px 10px;border:1px solid #cbd5e1;border-radius:7px;
  font-size:.78rem;outline:none;min-width:140px;
}}
.search:focus{{border-color:#3b82f6;}}

.timeline{{
  max-height:560px;overflow-y:auto;padding:0;
}}
.day{{
  padding:8px 18px;background:linear-gradient(90deg,#f1f5f9,#fff);
  font-family:'DM Mono',monospace;font-size:.76rem;color:#0f172a;font-weight:700;
  border-top:2px solid #e2e8f0;border-bottom:1px solid #e2e8f0;
  position:sticky;top:0;z-index:2;
}}
.day:first-child{{border-top:none;}}

.evt{{
  display:grid;grid-template-columns:28px 100px 34px 1fr 120px 120px;gap:10px;
  padding:9px 18px;border-bottom:1px solid #f1f5f9;align-items:center;
  font-size:.83rem;transition:background .1s;
}}
.evt:hover{{background:#f0f7ff;}}
.evt.hidden{{display:none;}}

.evt .icon{{font-size:1.05rem;text-align:center;}}
.evt-logo{{
  width:28px;height:28px;border-radius:50%;
  background:#000;
  border:1.2px solid rgba(148,163,184,.4);
  box-shadow:0 1px 3px rgba(0,0,0,.3),inset 0 0 0 1px rgba(255,255,255,.04);
  display:flex;align-items:center;justify-content:center;
  overflow:hidden;padding:3px;flex-shrink:0;
}}
.evt-logo img{{
  max-width:100%;max-height:100%;object-fit:contain;display:block;
}}
.evt-logo-fallback{{
  color:#94a3b8;font-family:'DM Mono',monospace;font-weight:700;
  font-size:.58rem;letter-spacing:.02em;padding:0;
}}
.evt-text{{min-width:0;overflow:hidden;}}
.evt .tk{{
  font-family:'DM Mono',monospace;font-weight:600;color:#1d4ed8;font-size:.78rem;
}}
.evt .nm{{color:#64748b;font-size:.78rem;}}
.evt .type-pill{{
  padding:2px 10px;border-radius:11px;font-size:.66rem;font-weight:700;letter-spacing:.04em;
  text-transform:uppercase;text-align:center;font-family:'DM Sans',sans-serif;
}}
.evt .type-pill.buy{{background:#dcfce7;color:#15803d;}}
.evt .type-pill.sell{{background:#fee2e2;color:#991b1b;}}
.evt .amount{{
  font-family:'DM Mono',monospace;font-size:.8rem;text-align:right;font-weight:600;
}}
.evt .amount.pos{{color:#16a34a;}}
.evt .amount.neg{{color:#dc2626;}}
.evt .amount.neutral{{color:#64748b;}}

.empty{{text-align:center;padding:40px;color:#94a3b8;font-size:.9rem;}}
</style>
</head>
<body>
<div class="shell">

  <div class="hdr">
    <span style="font-size:1.1rem;">🎬</span>
    <span class="title">Línia temporal de la cartera</span>
    <span class="sub">{date_from} → {date_to}</span>
  </div>

  <div class="toolbar">
    <span class="stat">📊 <strong>{n_assets}</strong> actius</span>
    <span class="stat"><span class="dot buy"></span><strong>{n_buys}</strong> compres</span>
    <span class="stat"><span class="dot sell"></span><strong>{n_sells}</strong> vendes</span>
    <span class="stat">📝 <strong>{n_events}</strong> esdeveniments</span>
    <input type="text" class="search" id="searchBox" placeholder="🔍 Cerca ticker…">
    <div class="filter-group">
      <button class="fbtn on" id="fAll" onclick="filter('all')">Tots</button>
      <button class="fbtn" id="fBuy" onclick="filter('buy')">Compres</button>
      <button class="fbtn" id="fSell" onclick="filter('sell')">Vendes</button>
    </div>
  </div>

  <div class="timeline" id="timeline"></div>
</div>

<script>
const EVS = {evs_json};

function fmt(v, d=2) {{
  if (v === null || v === undefined) return '—';
  return Number(v).toLocaleString('ca-ES', {{minimumFractionDigits:d, maximumFractionDigits:d}});
}}

function buildRow(e, idx) {{
  const isBuy = e.type === 'buy';
  const icon = isBuy ? '🟢' : '🔴';
  const pillCls = 'type-pill ' + e.type;
  const pillTxt = isBuy ? 'COMPRA' : 'VENDA';

  let amountHtml = '';
  if (isBuy) {{
    const sh = e.shares || 0;
    const inv = e.invested || 0;
    amountHtml = `<span class="amount neutral">${{sh}} acc.</span><span class="amount neutral">${{fmt(inv)}}€</span>`;
  }} else {{
    const pnl = e.pnl || 0;
    const ret = e.ret_pct || 0;
    const cls = pnl >= 0 ? 'pos' : 'neg';
    amountHtml = `<span class="amount ${{cls}}">${{pnl >= 0 ? '+' : ''}}${{fmt(pnl)}}€</span><span class="amount ${{cls}}">${{ret >= 0 ? '+' : ''}}${{fmt(ret,2)}}%</span>`;
  }}

  // Logo: cercle negre amb anell subtil. Si no n'hi ha, inicials del ticker.
  let logoHtml;
  if (e.logo_uri) {{
    logoHtml = `<div class="evt-logo"><img src="${{e.logo_uri}}" alt="${{e.ticker}}" /></div>`;
  }} else {{
    const initials = (e.ticker || '?').substring(0, 3).toUpperCase();
    logoHtml = `<div class="evt-logo evt-logo-fallback">${{initials}}</div>`;
  }}

  return `<div class="evt" data-tk="${{e.ticker}}" data-type="${{e.type}}" data-idx="${{idx}}">
    <span class="icon">${{icon}}</span>
    <span class="${{pillCls}}">${{pillTxt}}</span>
    ${{logoHtml}}
    <span class="evt-text"><span class="tk">${{e.ticker}}</span> · <span class="nm">${{e.company}}</span> · Preu <strong>${{fmt(e.price)}}</strong></span>
    ${{amountHtml}}
  </div>`;
}}

function render() {{
  const container = document.getElementById('timeline');
  container.innerHTML = '';
  let lastDay = null;
  let htmlBuf = '';
  EVS.forEach((e, idx) => {{
    const day = String(e.time).slice(0, 10);
    if (day !== lastDay) {{
      htmlBuf += `<div class="day">📅 ${{day}}</div>`;
      lastDay = day;
    }}
    htmlBuf += buildRow(e, idx);
  }});
  container.innerHTML = htmlBuf || '<div class="empty">Cap esdeveniment.</div>';
  applyFilters();
}}

let curFilter = 'all';
function filter(f) {{
  curFilter = f;
  document.querySelectorAll('.fbtn').forEach(b => b.classList.remove('on'));
  const mapping = {{all:'fAll', buy:'fBuy', sell:'fSell'}};
  document.getElementById(mapping[f]).classList.add('on');
  applyFilters();
}}

function applyFilters() {{
  const q = (document.getElementById('searchBox').value || '').toLowerCase().trim();
  document.querySelectorAll('.evt').forEach(row => {{
    const tk = (row.dataset.tk || '').toLowerCase();
    const tp = row.dataset.type;
    const matchType = curFilter === 'all' || tp === curFilter;
    const matchQ = !q || tk.includes(q);
    row.classList.toggle('hidden', !(matchType && matchQ));
  }});
}}

document.getElementById('searchBox').addEventListener('input', applyFilters);

render();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# MSCI WORLD — CARREGA D'ÍNDEX DE REFERÈNCIA
# ─────────────────────────────────────────────────────────────
def _build_equity_curve_html(
    equity_points: list,
    prices_df: pd.DataFrame,
    msci_df: pd.DataFrame | None,
    capital_inicial: float,
    title: str,
    subtitle: str = "",
) -> str:
    """
    Construeix un HTML interactiu amb 3 corbes superposades, totes
    normalitzades a base 100 al primer dia disponible:

      - Estratègia (corba d'equity del backtest)
      - Buy & Hold (preu × accions inicials del mateix actiu/cartera)
      - MSCI World (índex de referència)

    Paràmetres:
      equity_points: llista de {"time": "YYYY-MM-DD", "value": float}
      prices_df:     DataFrame amb Date, Close (per al B&H)
      msci_df:       DataFrame amb Date, Close (MSCI World) o None
      capital_inicial: capital base per normalitzar
      title:         títol del gràfic
      subtitle:      subtítol opcional
    """

    if not equity_points:
        return "<p style='color:#94a3b8;padding:20px;'>Sense dades d'equity per mostrar.</p>"

    # Dates del backtest (eix X)
    eq_dates = [p["time"] for p in equity_points]
    eq_values = [float(p["value"]) for p in equity_points]

    # Base 100: normalitzem l'estratègia dividint per capital_inicial
    eq_norm = [round(v / capital_inicial * 100.0, 3) for v in eq_values]

    # Buy & Hold: calculat dels preus diaris del mateix període
    bh_norm = []
    if prices_df is not None and not prices_df.empty:
        pdf = prices_df.copy()
        pdf["Date"] = pd.to_datetime(pdf["Date"])
        pdf = pdf.sort_values("Date").reset_index(drop=True)
        price_dates = pdf["Date"].dt.strftime("%Y-%m-%d").tolist()
        price_closes = pdf["Close"].tolist()

        # Alineem: per cada eq_date, trobem el close corresponent (o l'anterior)
        aligned_prices = _resample_index_to_dates(pdf.rename(columns={"Close": "Close"}), eq_dates)

        # Normalitzem al primer preu alineat
        base_price = next((p for p in aligned_prices if p is not None), None)
        if base_price and base_price > 0:
            bh_norm = [
                round((p / base_price * 100.0), 3) if p is not None else None
                for p in aligned_prices
            ]
        else:
            bh_norm = [None] * len(eq_dates)
    else:
        bh_norm = [None] * len(eq_dates)

    # MSCI World: alineat amb les dates del backtest
    msci_norm = []
    if msci_df is not None and not msci_df.empty:
        msci_aligned = _resample_index_to_dates(msci_df, eq_dates)
        base_msci = next((m for m in msci_aligned if m is not None), None)
        if base_msci and base_msci > 0:
            msci_norm = [
                round((m / base_msci * 100.0), 3) if m is not None else None
                for m in msci_aligned
            ]
        else:
            msci_norm = [None] * len(eq_dates)
    else:
        msci_norm = [None] * len(eq_dates)

    # Estadístiques finals
    strat_final = eq_norm[-1] if eq_norm else 100.0
    bh_final = next((v for v in reversed(bh_norm) if v is not None), None)
    msci_final = next((v for v in reversed(msci_norm) if v is not None), None)

    def _ret(v):
        return None if v is None else round(v - 100.0, 2)

    strat_ret = _ret(strat_final)
    bh_ret = _ret(bh_final)
    msci_ret = _ret(msci_final)

    def _fmt_ret(r):
        if r is None:
            return "—"
        sign = "+" if r >= 0 else ""
        return f"{sign}{r:.2f}%"

    strat_col = "#10b981" if (strat_ret or 0) >= 0 else "#ef4444"
    bh_col = "#3b82f6" if (bh_ret or 0) >= 0 else "#2563eb"
    msci_col = "#f59e0b"

    # Pre-calculem textos (evita expressions condicionals dins f-strings)
    strat_final_txt = f"{strat_final:.2f}"
    bh_final_txt = f"{bh_final:.2f}" if bh_final is not None else "—"
    msci_final_txt = f"Base 100 → {msci_final:.2f}" if msci_final is not None else "Dades no disponibles"

    dates_js = json.dumps(eq_dates)
    eq_js = json.dumps(eq_norm)
    bh_js = json.dumps(bh_norm)
    msci_js = json.dumps(msci_norm)

    msci_available = msci_df is not None and not msci_df.empty

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans',sans-serif;background:#0b1120;color:#e2e8f0;}}
.eq-shell{{border-radius:14px;overflow:hidden;border:1px solid #1e293b;box-shadow:0 6px 28px rgba(0,0,0,.55);}}

.eq-head{{
  background:linear-gradient(110deg,#0f172a,#1e3a5f);
  padding:14px 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  border-bottom:1px solid #1e293b;
}}
.eq-head .title{{font-size:1.02rem;font-weight:700;color:#f1f5f9;}}
.eq-head .subtitle{{font-size:.78rem;color:#94a3b8;margin-left:4px;}}

/* KPIs de comparació */
.eq-kpis{{
  background:#0f172a;padding:12px 18px;
  display:flex;gap:10px;flex-wrap:wrap;
  border-bottom:1px solid #1e293b;
}}
.kpi{{
  flex:1;min-width:160px;background:#1e293b;border:1px solid #334155;
  border-radius:10px;padding:10px 14px;
  display:flex;align-items:center;gap:10px;
}}
.kpi .dot{{width:12px;height:12px;border-radius:50%;flex-shrink:0;}}
.kpi .body{{flex:1;min-width:0;}}
.kpi .lbl{{font-size:.68rem;color:#94a3b8;font-weight:600;text-transform:uppercase;letter-spacing:.05em;}}
.kpi .val{{font-family:'DM Mono',monospace;font-size:1rem;font-weight:700;margin-top:2px;}}
.kpi .final{{font-size:.72rem;color:#64748b;margin-top:2px;font-family:'DM Mono',monospace;}}

/* Toolbar: períodes i toggles */
.eq-toolbar{{
  background:#0f172a;padding:8px 18px;border-bottom:1px solid #1e293b;
  display:flex;gap:6px;flex-wrap:wrap;align-items:center;
}}
.eq-pb{{
  font-family:'DM Sans',sans-serif;font-size:.73rem;font-weight:600;
  padding:5px 11px;border-radius:7px;border:1px solid #334155;
  background:transparent;color:#94a3b8;cursor:pointer;transition:all .13s;
}}
.eq-pb.on,.eq-pb:hover{{background:#1d4ed8;border-color:#1d4ed8;color:#fff;}}
.eq-sep{{width:1px;height:18px;background:#334155;margin:0 3px;}}
.eq-toggle{{
  font-size:.72rem;font-weight:600;padding:4px 11px;border-radius:7px;
  border:1px solid #334155;background:transparent;cursor:pointer;transition:all .13s;
  display:inline-flex;align-items:center;gap:6px;
}}
.eq-toggle .swatch{{width:10px;height:10px;border-radius:50%;}}
.eq-toggle.on{{background:rgba(59,130,246,.15);border-color:#3b82f6;color:#e2e8f0;}}
.eq-toggle.off{{opacity:.45;color:#64748b;}}

#eqChart{{background:#0b1120;}}
</style>
</head>
<body>
<div class="eq-shell">

  <div class="eq-head">
    <span style="font-size:1.2rem;">📈</span>
    <span class="title">{title}</span>
    {('<span class="subtitle">' + subtitle + '</span>') if subtitle else ''}
  </div>

  <div class="eq-kpis">
    <div class="kpi">
      <div class="dot" style="background:{strat_col};"></div>
      <div class="body">
        <div class="lbl">Estratègia</div>
        <div class="val" style="color:{strat_col};">{_fmt_ret(strat_ret)}</div>
        <div class="final">Base 100 → {strat_final_txt}</div>
      </div>
    </div>
    <div class="kpi">
      <div class="dot" style="background:{bh_col};"></div>
      <div class="body">
        <div class="lbl">Buy &amp; Hold</div>
        <div class="val" style="color:{bh_col};">{_fmt_ret(bh_ret)}</div>
        <div class="final">Base 100 → {bh_final_txt}</div>
      </div>
    </div>
    <div class="kpi">
      <div class="dot" style="background:{msci_col};"></div>
      <div class="body">
        <div class="lbl">MSCI World</div>
        <div class="val" style="color:{msci_col};">{_fmt_ret(msci_ret)}</div>
        <div class="final">{msci_final_txt}</div>
      </div>
    </div>
  </div>

  <div class="eq-toolbar">
    <button class="eq-pb on" data-days="99999" onclick="eqRange(this, 99999)">Tot</button>
    <button class="eq-pb" data-days="1825" onclick="eqRange(this, 1825)">5A</button>
    <button class="eq-pb" data-days="730" onclick="eqRange(this, 730)">2A</button>
    <button class="eq-pb" data-days="365" onclick="eqRange(this, 365)">1A</button>
    <button class="eq-pb" data-days="180" onclick="eqRange(this, 180)">6M</button>
    <button class="eq-pb" data-days="90" onclick="eqRange(this, 90)">3M</button>
    <div class="eq-sep"></div>
    <button class="eq-toggle on" id="togStrat" onclick="eqToggle('strat')">
      <span class="swatch" style="background:{strat_col};"></span>Estratègia
    </button>
    <button class="eq-toggle on" id="togBH" onclick="eqToggle('bh')">
      <span class="swatch" style="background:{bh_col};"></span>Buy &amp; Hold
    </button>
    <button class="eq-toggle {'on' if msci_available else 'off'}" id="togMsci" onclick="eqToggle('msci')">
      <span class="swatch" style="background:{msci_col};"></span>MSCI World
    </button>
    <div class="eq-sep"></div>
    <button class="eq-pb" id="btnPng" onclick="eqDownloadPng()"
            title="Descarrega aquest gràfic com a imatge PNG">
      📸 PNG
    </button>
  </div>

  <div id="eqChart"></div>
</div>

<script>
const DATES = {dates_js};
const EQ = {eq_js};
const BH = {bh_js};
const MSCI = {msci_js};

const chartDiv = document.getElementById('eqChart');
const H = 440;
chartDiv.style.height = H + 'px';
const W = () => chartDiv.offsetWidth || 900;

const chart = LightweightCharts.createChart(chartDiv, {{
  width: W(), height: H,
  layout: {{background:{{color:'#0b1120'}}, textColor:'#94a3b8'}},
  grid: {{vertLines:{{color:'#151f2e'}}, horzLines:{{color:'#151f2e'}}}},
  crosshair: {{
    mode: LightweightCharts.CrosshairMode.Magnet,
    vertLine: {{ color: 'rgba(148,163,184,.35)', width: 1, style: 3, labelBackgroundColor: '#1e293b' }},
    horzLine: {{ color: 'rgba(148,163,184,.35)', width: 1, style: 3, labelBackgroundColor: '#1e293b' }},
  }},
  rightPriceScale: {{borderColor:'#334155', scaleMargins: {{top: 0.08, bottom: 0.08}}}},
  timeScale: {{borderColor:'#334155', timeVisible:true}},
}});

// Línia de referència "base 100" — densificada per evitar artefactes
const refSeries = chart.addLineSeries({{
  color:'rgba(148,163,184,.35)', lineWidth:1, lineStyle:3,
  lastValueVisible:false, priceLineVisible:false, crosshairMarkerVisible:false,
}});
refSeries.setData(DATES.map(d => ({{time: d, value: 100}})));

// Funció per netejar arrays amb null/undefined eliminant els forats.
// IMPORTANT: lightweight-charts NO accepta value=NaN; els nulls han de
// quedar fora de les dades, no com a buit dins del data array.
function cleanLine(arr) {{
  const out = [];
  for (let i = 0; i < arr.length; i++) {{
    const v = arr[i];
    if (v !== null && v !== undefined && !isNaN(v) && isFinite(v)) {{
      out.push({{time: DATES[i], value: Number(v)}});
    }}
  }}
  return out;
}}

// ── Configuració comuna de les sèries ──
// • lastValueVisible: false       → cap pastilla flotant a la dreta
// • priceLineVisible: false       → cap línia horitzontal al preu actual
// • crosshairMarkerVisible: false → cap punt gros al moure el crosshair
// • lineType: 0 (Simple)          → tracen línies entre punts CONSECUTIUS
//                                   sense projecció més enllà del rang
// Aquestes opcions juntes eliminen totes les línies verticals "fantasma".
const COMMON_OPTS = {{
  priceLineVisible: false,
  lastValueVisible: false,
  crosshairMarkerVisible: false,
  lineType: 0,
}};

// Estratègia: línia sòlida contínua
const stratSeries = chart.addLineSeries({{
  ...COMMON_OPTS, color: '{strat_col}', lineWidth: 2.5,
}});
// Buy & Hold: línia sòlida contínua
const bhSeries = chart.addLineSeries({{
  ...COMMON_OPTS, color: '{bh_col}', lineWidth: 2,
}});
// MSCI World: línia discontínua (guions) com a referència
const msciSeries = chart.addLineSeries({{
  ...COMMON_OPTS, color: '{msci_col}', lineWidth: 2, lineStyle: 2,
}});

stratSeries.setData(cleanLine(EQ));
bhSeries.setData(cleanLine(BH));
msciSeries.setData(cleanLine(MSCI));

const visibility = {{strat:true, bh:true, msci:{str(msci_available).lower()}}};

function eqToggle(key) {{
  visibility[key] = !visibility[key];
  const map = {{strat:['togStrat', stratSeries, EQ],
               bh:['togBH', bhSeries, BH],
               msci:['togMsci', msciSeries, MSCI]}};
  const [btnId, series, data] = map[key];
  document.getElementById(btnId).classList.toggle('on', visibility[key]);
  document.getElementById(btnId).classList.toggle('off', !visibility[key]);
  series.setData(visibility[key] ? cleanLine(data) : []);
}}

function eqRange(btn, days) {{
  document.querySelectorAll('.eq-pb').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  if (days >= 99999) {{
    chart.timeScale().fitContent();
    return;
  }}
  const last = new Date(DATES[DATES.length - 1]);
  const from = new Date(last);
  from.setDate(from.getDate() - days);
  const fromStr = from.toISOString().slice(0, 10);
  const fromValid = DATES.find(d => d >= fromStr) || DATES[0];
  chart.timeScale().setVisibleRange({{from: fromValid, to: DATES[DATES.length - 1]}});
}}

chart.timeScale().fitContent();

// ── Descàrrega PNG ────────────────────────────────────────────
// Usa el mètode nadiu takeScreenshot() de Lightweight Charts, que
// retorna un canvas HTML. El convertim a Blob i el descarreguem amb
// una <a download>. Funciona offline; cap dependència externa.
function eqDownloadPng() {{
  try {{
    const canvas = chart.takeScreenshot();
    canvas.toBlob(function(blob) {{
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const ts = new Date().toISOString().slice(0,10);
      link.href = url;
      link.download = 'corba_capital_' + ts + '.png';
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {{
        URL.revokeObjectURL(url);
        link.remove();
      }}, 100);
    }}, 'image/png');
  }} catch (e) {{
    alert('Error generant el PNG: ' + e.message);
  }}
}}

new ResizeObserver(() => chart.applyOptions({{width: W()}})).observe(chartDiv);
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# MINI-CORBA DE CAPITAL PER ACTIU (usada a Resultat per actiu)
# ─────────────────────────────────────────────────────────────
def _build_mini_equity_svg(equity_points: list, capital_inicial: float,
                           prices_df: pd.DataFrame | None = None,
                           width: int = 260, height: int = 120) -> str:
    """
    Versió SVG INLINE (sense iframe) de la mini-corba de capital.
    Dissenyada per incrustar-se dins targetes quan es rendertzen moltes
    alhora (evita tenir 30+ iframes de lightweight-charts).

    Dues corbes normalitzades a base 100:
      • Estratègia (verd si guanya, vermell si perd) — gruixuda
      • Buy & Hold (blau) — fina
    Més una línia de referència horitzontal a base 100.
    """
    if not equity_points:
        return '<svg viewBox="0 0 260 120" xmlns="http://www.w3.org/2000/svg"></svg>'

    eq_values = [float(p["value"]) for p in equity_points]
    eq_norm = [v / capital_inicial * 100.0 for v in eq_values]

    # Buy & Hold alineat
    bh_norm = []
    if prices_df is not None and not prices_df.empty:
        pdf = prices_df.copy()
        pdf["Date"] = pd.to_datetime(pdf["Date"])
        pdf = pdf.sort_values("Date").reset_index(drop=True)
        eq_dates = [p["time"] for p in equity_points]
        aligned = _resample_index_to_dates(pdf, eq_dates)
        base = next((p for p in aligned if p is not None), None)
        if base and base > 0:
            bh_norm = [(p / base * 100.0) if p is not None else None for p in aligned]

    # Marge interior per respirar
    pad_x, pad_y = 6, 12
    inner_w = width - 2 * pad_x
    inner_h = height - 2 * pad_y

    # Rang Y: inclou les dues corbes i la referència 100
    all_vals = [v for v in eq_norm if v is not None]
    all_vals.extend([v for v in bh_norm if v is not None])
    all_vals.append(100.0)
    v_min = min(all_vals)
    v_max = max(all_vals)
    if v_max - v_min < 1e-6:
        v_min, v_max = v_min - 1, v_max + 1
    v_range = v_max - v_min

    n = len(eq_norm)

    def _y(val: float) -> float:
        return pad_y + (1.0 - (val - v_min) / v_range) * inner_h

    def _x(i: int) -> float:
        if n <= 1:
            return pad_x + inner_w / 2
        return pad_x + (i / (n - 1)) * inner_w

    # Path de l'estratègia
    eq_points = [f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(eq_norm)]
    eq_path = "M " + " L ".join(eq_points) if eq_points else ""

    # Path del B&H (pot tenir None → partim en trossos)
    bh_segments = []
    current = []
    for i, v in enumerate(bh_norm):
        if v is None:
            if len(current) >= 2:
                bh_segments.append("M " + " L ".join(current))
            current = []
        else:
            current.append(f"{_x(i):.1f},{_y(v):.1f}")
    if len(current) >= 2:
        bh_segments.append("M " + " L ".join(current))

    # Color estratègia
    strat_final = eq_norm[-1] if eq_norm else 100.0
    strat_col = "#10b981" if strat_final >= 100 else "#ef4444"

    # Línia de referència base 100
    ref_y = _y(100.0)

    # Retorn final per al label
    ret_txt = f"{strat_final - 100:+.1f}%"

    return f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none">
  <!-- Línia referència base 100 -->
  <line x1="{pad_x}" y1="{ref_y:.1f}" x2="{width - pad_x}" y2="{ref_y:.1f}"
        stroke="rgba(148,163,184,.35)" stroke-width="1" stroke-dasharray="3,3" />
  <!-- Buy & Hold (fina, blava) -->
  {''.join(f'<path d="{seg}" fill="none" stroke="#3b82f6" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" opacity=".7" />' for seg in bh_segments)}
  <!-- Estratègia (gruixuda, color segons resultat) -->
  <path d="{eq_path}" fill="none" stroke="{strat_col}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
  <!-- Label del retorn final -->
  <text x="{width - pad_x}" y="{pad_y + 2}" text-anchor="end"
        font-family="'DM Mono', monospace" font-size="10" font-weight="700" fill="{strat_col}">{ret_txt}</text>
</svg>"""


def _build_mini_equity_html(equity_points: list, capital_inicial: float,
                            prices_df: pd.DataFrame | None = None,
                            height: int = 180) -> str:
    """
    Mini-corba compacta amb 2 línies (Estratègia + B&H) normalitzades a base 100.
    Sense controls ni KPIs — disseny pensat per incrustar dins d'un card.
    """
    if not equity_points:
        return "<div style='color:#94a3b8;padding:12px;font-size:.78rem;'>Sense dades.</div>"

    eq_dates = [p["time"] for p in equity_points]
    eq_values = [float(p["value"]) for p in equity_points]
    eq_norm = [round(v / capital_inicial * 100.0, 3) for v in eq_values]

    # B&H alineat
    bh_norm = [None] * len(eq_dates)
    if prices_df is not None and not prices_df.empty:
        pdf = prices_df.copy()
        pdf["Date"] = pd.to_datetime(pdf["Date"])
        pdf = pdf.sort_values("Date").reset_index(drop=True)
        aligned = _resample_index_to_dates(pdf, eq_dates)
        base = next((p for p in aligned if p is not None), None)
        if base and base > 0:
            bh_norm = [round((p / base * 100.0), 3) if p is not None else None for p in aligned]

    strat_final = eq_norm[-1] if eq_norm else 100.0
    strat_col = "#10b981" if strat_final >= 100 else "#ef4444"

    dates_js = json.dumps(eq_dates)
    eq_js = json.dumps(eq_norm)
    bh_js = json.dumps(bh_norm)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#0b1120;}}
#mc{{background:#0b1120;border-radius:8px;overflow:hidden;}}
</style></head>
<body>
<div id="mc" style="height:{height}px;"></div>
<script>
const DATES={dates_js}, EQ={eq_js}, BH={bh_js};
const cDiv=document.getElementById('mc');
const chart=LightweightCharts.createChart(cDiv,{{
  width:cDiv.offsetWidth||400,height:{height},
  layout:{{background:{{color:'#0b1120'}},textColor:'#64748b',fontSize:9}},
  grid:{{vertLines:{{visible:false}},horzLines:{{color:'#151f2e'}}}},
  crosshair:{{mode:0}},
  rightPriceScale:{{borderColor:'#334155',scaleMargins:{{top:0.12,bottom:0.12}}}},
  timeScale:{{borderColor:'#334155',timeVisible:true}},
  handleScroll:false,handleScale:false,
}});

const clean=a=>a.map((v,i)=>v!==null&&v!==undefined?{{time:DATES[i],value:v}}:null).filter(Boolean);

const ref=chart.addLineSeries({{color:'rgba(148,163,184,.3)',lineWidth:1,lineStyle:3,
  lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false}});
ref.setData(DATES.map(d=>({{time:d,value:100}})));

const bh=chart.addLineSeries({{color:'#3b82f6',lineWidth:1.5,
  lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false}});
bh.setData(clean(BH));

const strat=chart.addLineSeries({{color:'{strat_col}',lineWidth:2,
  lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false}});
strat.setData(clean(EQ));

chart.timeScale().fitContent();
new ResizeObserver(()=>chart.applyOptions({{width:cDiv.offsetWidth}})).observe(cDiv);
</script>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# REPRODUCTOR BACKTEST — GRÀFIC ANIMAT AMB POPUP DE CRITERIS
# ─────────────────────────────────────────────────────────────
def _build_replay_chart_html(df: pd.DataFrame, ticker: str, company: str, result: dict) -> str:
    """
    Gràfic animat que reprodueix el backtest temporalment. Inclou:
      - Controls Play/Pausa, velocitat ajustable (dia a dia)
      - Botó "Següent operació" per saltar entre compres/vendes
      - Slider temporal manual
      - Popup flotant al costat de la vela amb TOTS els criteris
        complerts al moment de l'entrada (força del reversal, DSVWAP,
        ATR, distància en ATR, volatilitat, fracció decidida, accions…)
    """

    needed = {"Open", "High", "Low", "Close", "DSVWAP"}
    if not needed.issubset(df.columns):
        return "<p style='color:#ef4444;padding:20px;'>Falten columnes OHLC/indicadors.</p>"

    plot_df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy().reset_index(drop=True)
    if plot_df.empty:
        return "<p style='color:#ef4444;padding:20px;'>Sense dades per reproduir.</p>"

    dates_js = json.dumps([str(d)[:10] for d in plot_df["Date"]])
    o_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["Open"]])
    h_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["High"]])
    l_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["Low"]])
    c_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["Close"]])
    dsvwap_js = json.dumps([None if pd.isna(v) else round(float(v), 4) for v in plot_df["DSVWAP"]])

    # Volum (per al panell intermedi)
    if "Volume" in plot_df.columns:
        v_js = json.dumps([None if pd.isna(v) else float(v) for v in plot_df["Volume"]])
    else:
        v_js = "[]"

    # ATR% (14): ATR_rel × 100 (per al panell inferior)
    if "ATR_rel" in plot_df.columns:
        atr_pct_js = json.dumps([
            None if pd.isna(v) else round(float(v) * 100.0, 4)
            for v in plot_df["ATR_rel"]
        ])
    else:
        atr_pct_js = "[]"

    # Signals enriquits amb tots els criteris
    sig_js = json.dumps(result["signals"], ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{height:100%;}}
body{{font-family:'DM Sans',sans-serif;background:#0b1120;color:#e2e8f0;}}

.replay-shell{{border-radius:14px;overflow:hidden;border:1px solid #1e293b;box-shadow:0 6px 28px rgba(0,0,0,.55);display:flex;flex-direction:column;}}

/* HEADER */
.rp-top{{
  background:linear-gradient(110deg,#0f172a,#1e3a5f);
  padding:12px 18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  border-bottom:1px solid #1e293b;
}}
.rp-top .tk{{font-family:'DM Mono',monospace;font-size:.72rem;color:#60a5fa;letter-spacing:.12em;text-transform:uppercase;}}
.rp-top .nm{{font-size:1.02rem;font-weight:700;color:#f1f5f9;}}
.rp-badge{{background:rgba(168,85,247,.16);border:1px solid rgba(168,85,247,.4);color:#c084fc;font-size:.68rem;font-weight:700;padding:3px 10px;border-radius:20px;letter-spacing:.05em;text-transform:uppercase;}}
.rp-date-box{{margin-left:auto;text-align:right;}}
.rp-date{{font-family:'DM Mono',monospace;font-size:.95rem;font-weight:700;color:#f1f5f9;}}
.rp-pct{{font-size:.72rem;color:#94a3b8;margin-top:2px;}}

/* CONTROLS */
.rp-ctrl{{
  background:#0f172a;border-bottom:1px solid #1e293b;
  padding:10px 16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
}}
.rp-btn{{
  font-family:'DM Sans',sans-serif;font-size:.8rem;font-weight:600;
  padding:6px 14px;border-radius:8px;border:1px solid #334155;
  background:#1e293b;color:#e2e8f0;cursor:pointer;transition:all .14s;
  display:inline-flex;align-items:center;gap:6px;
}}
.rp-btn:hover{{background:#334155;border-color:#60a5fa;}}
.rp-btn.primary{{background:#1d4ed8;border-color:#1d4ed8;color:#fff;}}
.rp-btn.primary:hover{{background:#1e40af;}}
.rp-btn:disabled{{opacity:.4;cursor:not-allowed;}}
.rp-btn.playing{{background:#dc2626;border-color:#dc2626;}}
.rp-btn.playing:hover{{background:#b91c1c;}}

.rp-speed{{
  display:flex;align-items:center;gap:6px;
  font-size:.75rem;color:#94a3b8;
}}
.rp-speed select{{
  font-family:'DM Sans',sans-serif;font-size:.78rem;
  padding:5px 8px;border-radius:6px;border:1px solid #334155;
  background:#0b1120;color:#e2e8f0;cursor:pointer;outline:none;
}}

.rp-progress{{
  flex:1;min-width:220px;display:flex;align-items:center;gap:10px;
}}
.rp-progress input[type=range]{{
  flex:1;height:6px;appearance:none;background:#1e293b;border-radius:6px;outline:none;cursor:pointer;
}}
.rp-progress input[type=range]::-webkit-slider-thumb{{
  appearance:none;width:16px;height:16px;border-radius:50%;background:#60a5fa;
  cursor:pointer;border:2px solid #0b1120;box-shadow:0 0 0 1px #60a5fa;
}}
.rp-progress input[type=range]::-moz-range-thumb{{
  width:16px;height:16px;border-radius:50%;background:#60a5fa;
  cursor:pointer;border:2px solid #0b1120;
}}
.rp-counter{{
  font-family:'DM Mono',monospace;font-size:.75rem;color:#94a3b8;white-space:nowrap;
}}

/* LEGEND */
.rp-legend{{
  display:flex;gap:14px;align-items:center;font-size:.72rem;color:#94a3b8;
  padding:7px 16px;background:#0f172a;border-bottom:1px solid #1e293b;
}}
.rp-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle;}}
.rp-sig-count{{margin-left:auto;font-family:'DM Mono',monospace;color:#cbd5e1;}}

/* CHART */
.rp-chart-wrap{{position:relative;background:#0b1120;}}
#rpChart{{background:#0b1120;min-height:380px;}}
#rpVol{{background:#0b1120;border-top:1px solid #151f2e;min-height:110px;}}
#rpAtr{{background:#0b1120;border-top:1px solid #151f2e;position:relative;min-height:140px;}}
.rp-atr-label{{
  position:absolute;top:6px;left:10px;z-index:5;pointer-events:none;
  font-family:'DM Mono',monospace;font-size:.7rem;color:#ef4444;
  font-weight:600;letter-spacing:.02em;
}}
.rp-atr-label .lbl{{color:#94a3b8;font-weight:500;margin-right:4px;}}

/* ── Tooltip al hover de marcadors al reproductor ── */
.rp-tip{{
  position:absolute;z-index:60;pointer-events:none;
  background:#fff;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.55);
  padding:0;overflow:hidden;width:260px;
  font-family:'DM Sans',sans-serif;color:#1e293b;
  opacity:0;transform:translateY(4px);transition:opacity .13s,transform .13s;
}}
.rp-tip.visible{{opacity:1;transform:translateY(0);}}
.rp-tip .tip-head{{
  padding:7px 12px;color:#fff;font-weight:700;font-size:.76rem;
  display:flex;align-items:center;gap:6px;
}}
.rp-tip.buy .tip-head{{background:linear-gradient(100deg,#15803d,#22c55e);}}
.rp-tip.sell .tip-head{{background:linear-gradient(100deg,#991b1b,#ef4444);}}
.rp-tip .tip-head .date{{margin-left:auto;font-family:'DM Mono',monospace;font-size:.66rem;opacity:.94;font-weight:500;}}
.rp-tip .tip-body{{padding:7px 12px;}}
.rp-tip .row{{display:flex;justify-content:space-between;padding:2px 0;font-size:.72rem;border-bottom:1px dashed #e2e8f0;}}
.rp-tip .row:last-child{{border-bottom:none;}}
.rp-tip .k{{color:#64748b;font-weight:500;}}
.rp-tip .v{{font-family:'DM Mono',monospace;font-weight:700;color:#0f172a;font-size:.7rem;}}
.rp-tip .v.ok{{color:#16a34a;}}
.rp-tip .v.bad{{color:#dc2626;}}
.rp-tip .v.warn{{color:#d97706;}}

/* POPUP */
.rp-popup{{
  position:absolute;z-index:10;
  background:#fff;color:#1e293b;
  border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,.55);
  font-family:'DM Sans',sans-serif;
  width:340px;overflow:hidden;
  transition:opacity .18s, transform .18s;
  opacity:0;pointer-events:none;transform:translateY(4px);
}}
.rp-popup.show{{opacity:1;pointer-events:auto;transform:translateY(0);}}
.rp-popup.buy{{border-top:4px solid #10b981;}}
.rp-popup.sell{{border-top:4px solid #ef4444;}}
.rp-popup-head{{padding:12px 16px 10px;border-bottom:1px solid #e2e8f0;}}
.rp-pop-type{{
  display:inline-block;font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  padding:3px 10px;border-radius:20px;margin-bottom:6px;
}}
.rp-pop-type.buy{{background:#d1fae5;color:#065f46;}}
.rp-pop-type.sell{{background:#fee2e2;color:#991b1b;}}
.rp-pop-title{{font-size:1.02rem;font-weight:700;color:#0f172a;letter-spacing:-.01em;}}
.rp-pop-sub{{font-family:'DM Mono',monospace;font-size:.72rem;color:#64748b;margin-top:2px;}}

.rp-pop-section{{padding:10px 16px;border-bottom:1px solid #f1f5f9;}}
.rp-pop-section:last-child{{border-bottom:none;padding-bottom:14px;}}
.rp-pop-sec-title{{
  font-size:.64rem;font-weight:700;color:#64748b;
  text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px;
}}

.rp-pop-row{{
  display:flex;justify-content:space-between;align-items:baseline;
  padding:3px 0;gap:8px;font-size:.82rem;
}}
.rp-pop-key{{color:#475569;font-weight:500;flex-shrink:0;}}
.rp-pop-val{{font-family:'DM Mono',monospace;font-weight:600;color:#0f172a;text-align:right;}}
.rp-pop-val.good{{color:#059669;}}
.rp-pop-val.bad{{color:#dc2626;}}
.rp-pop-val.warn{{color:#d97706;}}
.rp-pop-val.info{{color:#2563eb;}}

.rp-pop-check{{
  display:flex;align-items:center;gap:8px;padding:4px 0;
  font-size:.78rem;color:#0f172a;
}}
.rp-pop-check::before{{
  content:'✓';color:#10b981;font-weight:700;font-size:.95rem;
}}
.rp-pop-check.miss{{color:#94a3b8;}}
.rp-pop-check.miss::before{{content:'○';color:#cbd5e1;}}

.rp-pop-close{{
  position:absolute;top:8px;right:10px;width:22px;height:22px;
  border-radius:50%;background:transparent;border:none;
  color:#94a3b8;font-size:1.1rem;font-weight:600;cursor:pointer;
  display:flex;align-items:center;justify-content:center;line-height:1;
}}
.rp-pop-close:hover{{background:#f1f5f9;color:#0f172a;}}

.rp-pop-frac-bar{{
  height:8px;background:#f1f5f9;border-radius:4px;overflow:hidden;margin-top:6px;
}}
.rp-pop-frac-fill{{
  height:100%;background:linear-gradient(90deg,#60a5fa,#1d4ed8);
  transition:width .3s;
}}
.rp-pop-frac-fill.leverage{{background:linear-gradient(90deg,#a78bfa,#7c3aed);}}

.rp-empty{{
  text-align:center;padding:36px 16px;color:#64748b;font-size:.83rem;
}}
</style>
</head>
<body>
<div class="replay-shell">
  <!-- HEADER -->
  <div class="rp-top">
    <div>
      <div class="tk">{ticker}</div>
      <div class="nm">{company}</div>
    </div>
    <div class="rp-badge">🎬 Replay Backtest</div>
    <div class="rp-date-box">
      <div class="rp-date" id="rpCurDate">—</div>
      <div class="rp-pct" id="rpProgress">0 / 0</div>
    </div>
  </div>

  <!-- CONTROLS -->
  <div class="rp-ctrl">
    <button class="rp-btn" id="rpRestart" title="Reinicia">⏮</button>
    <button class="rp-btn" id="rpPrevSig" title="Operació anterior">⏪</button>
    <button class="rp-btn primary" id="rpPlay" title="Play/Pausa">▶ Play</button>
    <button class="rp-btn" id="rpNextSig" title="Següent operació">⏩</button>
    <button class="rp-btn" id="rpEnd" title="Al final">⏭</button>

    <div class="rp-speed">
      <span>Velocitat:</span>
      <select id="rpSpeed">
        <option value="500">0.5×</option>
        <option value="200" selected>1×</option>
        <option value="100">2×</option>
        <option value="50">5×</option>
        <option value="20">10×</option>
      </select>
    </div>

    <div class="rp-progress">
      <input type="range" id="rpSlider" min="0" max="100" value="0">
      <span class="rp-counter" id="rpCounter">0/0</span>
    </div>

    <button class="rp-btn" id="rpPng" title="Descarrega aquest gràfic com a imatge PNG"
            onclick="rpDownloadPng()">📸 PNG</button>
  </div>

  <!-- LEGEND -->
  <div class="rp-legend">
    <span><span class="rp-dot" style="background:#3b82f6;"></span>DSVWAP</span>
    <span><span class="rp-dot" style="background:#34d399;"></span>Compra</span>
    <span><span class="rp-dot" style="background:#f87171;"></span>Venda</span>
    <span class="rp-sig-count" id="rpSigCount">0 senyals</span>
  </div>

  <!-- CHART + POPUP -->
  <div class="rp-chart-wrap">
    <div id="rpChart"></div>
    <div id="rpVol"></div>
    <div id="rpAtr">
      <div class="rp-atr-label"><span class="lbl">ATR% (14)</span><span id="rpAtrCurVal">—</span></div>
    </div>
    <div class="rp-popup" id="rpPopup">
      <button class="rp-pop-close" id="rpPopClose">×</button>
      <div id="rpPopContent"></div>
    </div>
    <div class="rp-tip" id="rpTip">
      <div class="tip-head">
        <span id="rpTipIcon">🟢</span>
        <span id="rpTipTitle">COMPRA</span>
        <span class="date" id="rpTipDate"></span>
      </div>
      <div class="tip-body" id="rpTipBody"></div>
    </div>
  </div>
</div>

<script>
// ── DATA ─────────────────────────────────────────────
const DATES  = {dates_js};
const OPEN_  = {o_js};
const HIGH_  = {h_js};
const LOW_   = {l_js};
const CLOSE_ = {c_js};
const DSVWAP = {dsvwap_js};
const VOL    = {v_js};
const ATR_PCT = {atr_pct_js};
const SIGNALS = {sig_js};

const N = DATES.length;
const SIG_MAP = new Map();
SIGNALS.forEach(s => {{
  if (!SIG_MAP.has(s.time)) SIG_MAP.set(s.time, []);
  SIG_MAP.get(s.time).push(s);
}});

// ── STATE ────────────────────────────────────────────
let curIdx = Math.min(30, N - 1);  // Comencem amb 30 barres visibles
let playing = false;
let playTimer = null;
let playInterval = 200;
let popupSignal = null;
let popupStickyUntil = 0;  // Timestamp durant el qual el popup no es pot tancar automàticament

// ── CHART INIT ───────────────────────────────────────
const chartDiv = document.getElementById('rpChart');
const volDiv = document.getElementById('rpVol');
const atrDiv = document.getElementById('rpAtr');
// Alçades fixes per garantir visibilitat dels 3 panells
const chartH = Math.max(400, Math.round(window.innerHeight * 0.50));
const volH = Math.max(110, Math.round(chartH * 0.24));
const atrH = Math.max(140, Math.round(chartH * 0.28));
volDiv.style.height = volH + 'px';
atrDiv.style.height = atrH + 'px';
const W = () => chartDiv.offsetWidth || 900;

const chart = LightweightCharts.createChart(chartDiv, {{
  width: W(), height: chartH,
  layout: {{background: {{color: '#0b1120'}}, textColor: '#94a3b8'}},
  grid: {{vertLines: {{color: '#151f2e'}}, horzLines: {{color: '#151f2e'}}}},
  crosshair: {{mode: LightweightCharts.CrosshairMode.Normal}},
  rightPriceScale: {{borderColor: '#334155'}},
  timeScale: {{borderColor: '#334155', timeVisible: true, barSpacing: 8}},
}});

// Panell de VOLUM
const volChart = LightweightCharts.createChart(volDiv, {{
  width: W(), height: volH,
  layout: {{background: {{color: '#0b1120'}}, textColor: '#475569'}},
  grid: {{vertLines: {{color: '#151f2e'}}, horzLines: {{color: '#151f2e'}}}},
  rightPriceScale: {{borderColor: '#334155', scaleMargins: {{top: 0.1, bottom: 0.0}}}},
  timeScale: {{borderColor: '#334155', timeVisible: true, visible: false}},
}});
const volSeries = volChart.addHistogramSeries({{priceFormat: {{type: 'volume'}}}});

// Panell d'ATR%
const atrChart = LightweightCharts.createChart(atrDiv, {{
  width: W(), height: atrH,
  layout: {{background: {{color: '#0b1120'}}, textColor: '#475569'}},
  grid: {{vertLines: {{color: '#151f2e'}}, horzLines: {{color: '#151f2e'}}}},
  rightPriceScale: {{borderColor: '#334155', scaleMargins: {{top: 0.1, bottom: 0.05}}}},
  timeScale: {{borderColor: '#334155', timeVisible: true}},
}});
const atrSeries = atrChart.addLineSeries({{
  color: '#ef4444', lineWidth: 1.5,
  lastValueVisible: true, priceLineVisible: false,
  crosshairMarkerVisible: false,
  priceFormat: {{type: 'price', precision: 2, minMove: 0.01}},
}});

const candleSeries = chart.addCandlestickSeries({{
  upColor: '#34d399', downColor: '#f87171',
  borderUpColor: '#34d399', borderDownColor: '#f87171',
  wickUpColor: '#34d399', wickDownColor: '#f87171',
}});

const dsSeries = chart.addLineSeries({{
  color: '#3b82f6', lineWidth: 2,
  lastValueVisible: true, priceLineVisible: false,
}});

// Sincronització de timescale entre els 3 panells
chart.timeScale().subscribeVisibleLogicalRangeChange(r => {{
  if (r) {{
    volChart.timeScale().setVisibleLogicalRange(r);
    atrChart.timeScale().setVisibleLogicalRange(r);
  }}
}});

// ── RENDER ───────────────────────────────────────────
function renderUpTo(idx) {{
  idx = Math.max(0, Math.min(N - 1, idx));
  curIdx = idx;

  // Dades de velles, DSVWAP, volum i ATR% fins a idx (inclusiu)
  const candles = [];
  const dsLine = [];
  const volBars = [];
  const atrLine = [];
  for (let i = 0; i <= idx; i++) {{
    if (OPEN_[i] !== null) {{
      candles.push({{
        time: DATES[i],
        open: OPEN_[i], high: HIGH_[i], low: LOW_[i], close: CLOSE_[i],
      }});
    }}
    if (DSVWAP[i] !== null) {{
      dsLine.push({{time: DATES[i], value: DSVWAP[i]}});
    }}
    if (VOL[i] !== null && VOL[i] !== undefined) {{
      const isUp = (CLOSE_[i] !== null && OPEN_[i] !== null && CLOSE_[i] >= OPEN_[i]);
      volBars.push({{
        time: DATES[i],
        value: VOL[i],
        color: isUp ? 'rgba(52,211,153,.45)' : 'rgba(248,113,113,.45)',
      }});
    }}
    if (ATR_PCT[i] !== null && ATR_PCT[i] !== undefined) {{
      atrLine.push({{time: DATES[i], value: ATR_PCT[i]}});
    }}
  }}
  candleSeries.setData(candles);
  dsSeries.setData(dsLine);
  volSeries.setData(volBars);
  atrSeries.setData(atrLine);

  // Actualitza la llegenda del valor ATR actual
  if (atrLine.length > 0) {{
    const lastAtr = atrLine[atrLine.length - 1].value;
    const el = document.getElementById('rpAtrCurVal');
    if (el) el.textContent = Number(lastAtr).toFixed(2) + '%';
  }}

  // Marcadors visibles (només fins a idx)
  const markers = [];
  for (let i = 0; i <= idx; i++) {{
    const sigs = SIG_MAP.get(DATES[i]);
    if (!sigs) continue;
    sigs.forEach(s => {{
      markers.push({{
        time: s.time,
        position: s.type === 'buy' ? 'belowBar' : 'aboveBar',
        color: s.type === 'buy' ? '#34d399' : '#f87171',
        shape: s.type === 'buy' ? 'arrowUp' : 'arrowDown',
        text: s.type === 'buy' ? 'C' : 'V',
        size: 1.3,
      }});
    }});
  }}
  markers.sort((a, b) => a.time < b.time ? -1 : 1);
  candleSeries.setMarkers(markers);

  // UI controls
  document.getElementById('rpSlider').value = idx;
  document.getElementById('rpCurDate').textContent = DATES[idx] || '—';
  document.getElementById('rpCounter').textContent = `${{idx + 1}}/${{N}}`;
  const pct = ((idx + 1) / N * 100).toFixed(1);
  document.getElementById('rpProgress').textContent = `${{pct}}% del període`;

  // Autoscroll: mantenim les darreres ~120 barres visibles
  try {{
    const visibleBars = 120;
    const fromIdx = Math.max(0, idx - visibleBars);
    const toIdx = Math.min(N - 1, idx + 5);
    chart.timeScale().setVisibleRange({{from: DATES[fromIdx], to: DATES[toIdx]}});
  }} catch (e) {{}}

  // El popup gran s'ha eliminat: la info de senyals es veu passant el ratolí
  // per sobre del marcador (tooltip compacte del reproductor).
  // Assegurem que el popup quedi ocult durant la reproducció automàtica.
  hidePopup();
}}

// ── POPUP ────────────────────────────────────────────
function fmt(v, dec = 2) {{
  if (v === null || v === undefined || isNaN(v)) return '—';
  return Number(v).toFixed(dec);
}}
function fmtMoney(v) {{
  if (v === null || v === undefined || isNaN(v)) return '—';
  return Number(v).toLocaleString('ca-ES', {{minimumFractionDigits: 2, maximumFractionDigits: 2}}) + '€';
}}
function fmtPct(v, dec = 2) {{
  if (v === null || v === undefined || isNaN(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return sign + Number(v).toFixed(dec) + '%';
}}

function buildBuyPopup(s) {{
  const distAtr = s.dsvwap_dist_atr;
  const bullStr = s.bull_strength;
  const atrRel = s.atr_rel_pct;

  // Avaluació qualitativa de cada criteri
  const c1Pass = bullStr !== null && bullStr >= 1.0;
  const c2Pass = s.close !== null && s.dsvwap !== null && s.close > s.dsvwap;
  const rsRev = bullStr !== null ? (bullStr >= 1.5 ? 'strong' : bullStr >= 1.2 ? 'mid' : 'weak') : null;
  const rsDist = distAtr !== null ? (distAtr >= 1.0 ? 'strong' : distAtr >= 0.5 ? 'mid' : 'weak') : null;
  const rsAtr = atrRel !== null ? (atrRel < 3 ? 'calm' : atrRel < 5 ? 'mid' : 'hot') : null;

  return `
    <div class="rp-popup-head">
      <span class="rp-pop-type buy">▲ COMPRA</span>
      <div class="rp-pop-title">Senyal d'entrada confirmat</div>
      <div class="rp-pop-sub">${{s.time}} · Preu ${{fmt(s.close, 2)}} €</div>
    </div>

    <div class="rp-pop-section">
      <div class="rp-pop-sec-title">📋 Criteris d'entrada</div>
      <div class="rp-pop-check ${{c1Pass ? '' : 'miss'}}">
        Bullish reversal detectat ${{bullStr !== null ? `(força ${{fmt(bullStr, 2)}}×)` : ''}}
      </div>
      <div class="rp-pop-check ${{c2Pass ? '' : 'miss'}}">
        Close > DSVWAP ${{s.close !== null && s.dsvwap !== null ? `(${{fmt(s.close, 2)}} > ${{fmt(s.dsvwap, 2)}})` : ''}}
      </div>
    </div>

    <div class="rp-pop-section">
      <div class="rp-pop-sec-title">📊 Força del senyal</div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Força reversal</span>
        <span class="rp-pop-val ${{rsRev === 'strong' ? 'good' : rsRev === 'mid' ? 'info' : 'warn'}}">
          ${{bullStr !== null ? fmt(bullStr, 2) + '×' : '—'}}
          ${{rsRev === 'strong' ? ' · fort' : rsRev === 'mid' ? ' · moderat' : rsRev === 'weak' ? ' · just' : ''}}
        </span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Distància al DSVWAP</span>
        <span class="rp-pop-val info">
          ${{distAtr !== null ? fmt(distAtr, 2) + ' ATR' : '—'}}
          ${{rsDist === 'strong' ? ' · fort' : rsDist === 'mid' ? ' · moderat' : rsDist === 'weak' ? ' · just' : ''}}
        </span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Volatilitat (ATR/preu)</span>
        <span class="rp-pop-val ${{rsAtr === 'calm' ? 'good' : rsAtr === 'mid' ? 'info' : 'warn'}}">
          ${{atrRel !== null ? fmt(atrRel, 2) + '%' : '—'}}
          ${{rsAtr === 'calm' ? ' · calma' : rsAtr === 'mid' ? ' · normal' : rsAtr === 'hot' ? ' · alta' : ''}}
        </span>
      </div>
    </div>

    <div class="rp-pop-section">
      <div class="rp-pop-sec-title">💼 Posició oberta</div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Capital disponible</span>
        <span class="rp-pop-val">${{fmtMoney(s.capital_pre)}}</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Accions comprades</span>
        <span class="rp-pop-val">${{s.shares || 0}}</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">€ Invertits</span>
        <span class="rp-pop-val info">${{fmtMoney(s.invested)}}</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">€ En cash residual</span>
        <span class="rp-pop-val">${{fmtMoney(s.cash_held)}}</span>
      </div>
    </div>
  `;
}}

function buildSellPopup(s) {{
  const pnl = s.pnl || 0;
  const retPct = s.ret_pct || 0;
  const pnlGood = pnl >= 0;
  return `
    <div class="rp-popup-head">
      <span class="rp-pop-type sell">▼ VENDA</span>
      <div class="rp-pop-title">Senyal de sortida confirmat</div>
      <div class="rp-pop-sub">${{s.time}} · Preu ${{fmt(s.close, 2)}} €</div>
    </div>

    <div class="rp-pop-section">
      <div class="rp-pop-sec-title">📋 Criteris de sortida</div>
      <div class="rp-pop-check">Bearish reversal detectat${{s.bear_strength !== null ? ` (força ${{fmt(s.bear_strength, 2)}}×)` : ''}}</div>
      <div class="rp-pop-check">Close < DSVWAP (${{fmt(s.close, 2)}} < ${{fmt(s.dsvwap, 2)}})</div>
    </div>

    <div class="rp-pop-section">
      <div class="rp-pop-sec-title">💰 Resultat de l'operació</div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Entrada</span>
        <span class="rp-pop-val">${{s.entry_date}} @ ${{fmt(s.entry_price, 2)}} €</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Durada</span>
        <span class="rp-pop-val">${{s.days}} dies</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Accions</span>
        <span class="rp-pop-val">${{s.shares || 0}}</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">P/L</span>
        <span class="rp-pop-val ${{pnlGood ? 'good' : 'bad'}}">${{pnlGood ? '+' : ''}}${{fmtMoney(pnl)}}</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Retorn</span>
        <span class="rp-pop-val ${{pnlGood ? 'good' : 'bad'}}">${{fmtPct(retPct)}}</span>
      </div>
      <div class="rp-pop-row">
        <span class="rp-pop-key">Capital post-venda</span>
        <span class="rp-pop-val info">${{fmtMoney(s.capital_out)}}</span>
      </div>
    </div>
  `;
}}

function showPopup(sig) {{
  popupSignal = sig;
  const popup = document.getElementById('rpPopup');
  const content = document.getElementById('rpPopContent');

  popup.classList.remove('buy', 'sell');
  popup.classList.add(sig.type);
  content.innerHTML = sig.type === 'buy' ? buildBuyPopup(sig) : buildSellPopup(sig);

  // Posició: a sobre del gràfic, a la dreta però amb marge perquè no surti
  const wrapRect = chartDiv.getBoundingClientRect();
  const popupWidth = 340;
  const padding = 16;
  // Sobre la dreta per defecte; si el chart és estret, a l'esquerra
  popup.style.top = (padding + 10) + 'px';
  popup.style.right = (padding + 70) + 'px';
  popup.style.left = 'auto';

  popup.classList.add('show');
  // Sticky: no es tanca automàticament els propers 5 segons
  popupStickyUntil = Date.now() + 5000;
}}

function hidePopup() {{
  document.getElementById('rpPopup').classList.remove('show');
  popupSignal = null;
}}

document.getElementById('rpPopClose').addEventListener('click', () => {{
  hidePopup();
  popupStickyUntil = 0;
}});

// ── PLAY / PAUSE / NAVIGATION ────────────────────────
function play() {{
  if (playing) return;
  playing = true;
  const btn = document.getElementById('rpPlay');
  btn.classList.add('playing');
  btn.innerHTML = '⏸ Pausa';
  playTimer = setInterval(() => {{
    if (curIdx >= N - 1) {{ pause(); return; }}
    renderUpTo(curIdx + 1);
  }}, playInterval);
}}

function pause() {{
  playing = false;
  const btn = document.getElementById('rpPlay');
  btn.classList.remove('playing');
  btn.innerHTML = '▶ Play';
  if (playTimer) {{ clearInterval(playTimer); playTimer = null; }}
}}

function togglePlay() {{ playing ? pause() : play(); }}

function nextSignal() {{
  for (let i = curIdx + 1; i < N; i++) {{
    if (SIG_MAP.has(DATES[i])) {{ pause(); renderUpTo(i); return; }}
  }}
  renderUpTo(N - 1);
}}

function prevSignal() {{
  for (let i = curIdx - 1; i >= 0; i--) {{
    if (SIG_MAP.has(DATES[i])) {{ pause(); renderUpTo(i); return; }}
  }}
  renderUpTo(0);
}}

document.getElementById('rpPlay').addEventListener('click', togglePlay);
document.getElementById('rpRestart').addEventListener('click', () => {{
  pause(); renderUpTo(Math.min(30, N - 1));
}});
document.getElementById('rpEnd').addEventListener('click', () => {{
  pause(); renderUpTo(N - 1);
}});
document.getElementById('rpNextSig').addEventListener('click', nextSignal);
document.getElementById('rpPrevSig').addEventListener('click', prevSignal);

document.getElementById('rpSlider').addEventListener('input', (e) => {{
  pause();
  renderUpTo(parseInt(e.target.value, 10));
}});

document.getElementById('rpSpeed').addEventListener('change', (e) => {{
  playInterval = parseInt(e.target.value, 10);
  if (playing) {{ pause(); play(); }}
}});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.code === 'Space') {{ e.preventDefault(); togglePlay(); }}
  else if (e.code === 'ArrowRight') {{ e.preventDefault(); pause(); renderUpTo(curIdx + 1); }}
  else if (e.code === 'ArrowLeft') {{ e.preventDefault(); pause(); renderUpTo(curIdx - 1); }}
  else if (e.code === 'KeyN') {{ e.preventDefault(); nextSignal(); }}
  else if (e.code === 'KeyP') {{ e.preventDefault(); prevSignal(); }}
}});

// ── Tooltip al passar el ratolí per sobre de marcadors ──
const rpTip = document.getElementById('rpTip');
const SIGNALS_BY_TIME = {{}};
SIGNALS.forEach(s => {{ SIGNALS_BY_TIME[String(s.time).replace(' *','')] = s; }});

function _fmtN(v, d=2) {{
  if (v === null || v === undefined) return '—';
  return Number(v).toLocaleString('ca-ES', {{minimumFractionDigits:d, maximumFractionDigits:d}});
}}

function _buildTipBody(s) {{
  const rows = [];
  if (s.type === 'buy') {{
    if (s.bull_strength !== null && s.bull_strength !== undefined) {{
      const cls = s.bull_strength >= 1.5 ? 'ok' : (s.bull_strength >= 1.2 ? 'warn' : '');
      rows.push(`<div class="row"><span class="k">✓ Bullish reversal</span><span class="v ${{cls}}">${{s.bull_strength.toFixed(2)}}× llindar</span></div>`);
    }}
    if (s.dsvwap_dist_atr !== null && s.dsvwap_dist_atr !== undefined) {{
      const cls = s.dsvwap_dist_atr >= 1.0 ? 'ok' : (s.dsvwap_dist_atr >= 0.3 ? 'warn' : '');
      rows.push(`<div class="row"><span class="k">✓ Close &gt; DSVWAP</span><span class="v ${{cls}}">+${{_fmtN(s.dsvwap_dist_atr,2)}} ATR</span></div>`);
    }}
    rows.push(`<div class="row"><span class="k">Preu exec.</span><span class="v">${{_fmtN(s.close)}}</span></div>`);
    if (s.shares !== undefined) rows.push(`<div class="row"><span class="k">Accions</span><span class="v">${{s.shares}}</span></div>`);
    if (s.invested !== undefined) rows.push(`<div class="row"><span class="k">€ Invertits</span><span class="v">${{_fmtN(s.invested)}}€</span></div>`);
    if (s.delay_bars !== undefined && s.delay_bars > 0) {{
      rows.push(`<div class="row"><span class="k">Senyal original</span><span class="v">${{s.signal_date}}</span></div>`);
      rows.push(`<div class="row"><span class="k">Retard confirm.</span><span class="v">${{s.delay_bars}} barra${{s.delay_bars > 1 ? 's' : ''}}</span></div>`);
    }}
  }} else {{
    if (s.bear_strength !== null && s.bear_strength !== undefined) {{
      rows.push(`<div class="row"><span class="k">✓ Bearish reversal</span><span class="v">${{s.bear_strength.toFixed(2)}}× llindar</span></div>`);
    }}
    if (s.dsvwap_dist_atr !== null && s.dsvwap_dist_atr !== undefined) {{
      rows.push(`<div class="row"><span class="k">✓ Close &lt; DSVWAP</span><span class="v">${{_fmtN(s.dsvwap_dist_atr,2)}} ATR</span></div>`);
    }}
    rows.push(`<div class="row"><span class="k">Preu exec.</span><span class="v">${{_fmtN(s.close)}}</span></div>`);
    rows.push(`<div class="row"><span class="k">Entrada</span><span class="v">${{s.entry_date}} · ${{_fmtN(s.entry_price)}}</span></div>`);
    rows.push(`<div class="row"><span class="k">Dies</span><span class="v">${{s.days || 0}}</span></div>`);
    const pnl = s.pnl ?? 0;
    const ret = s.ret_pct ?? 0;
    const cls = pnl >= 0 ? 'ok' : 'bad';
    rows.push(`<div class="row"><span class="k">P/L</span><span class="v ${{cls}}">${{pnl >= 0 ? '+' : ''}}${{_fmtN(pnl)}}€</span></div>`);
    rows.push(`<div class="row"><span class="k">Retorn</span><span class="v ${{cls}}">${{ret >= 0 ? '+' : ''}}${{_fmtN(ret,2)}}%</span></div>`);
    if (s.delay_bars !== undefined && s.delay_bars > 0) {{
      rows.push(`<div class="row"><span class="k">Retard confirm.</span><span class="v">${{s.delay_bars}} barra${{s.delay_bars > 1 ? 's' : ''}}</span></div>`);
    }}
  }}
  return rows.join('');
}}

function showRpTip(s, px, py) {{
  rpTip.className = 'rp-tip ' + s.type + ' visible';
  document.getElementById('rpTipIcon').textContent = s.type === 'buy' ? '🟢' : '🔴';
  document.getElementById('rpTipTitle').textContent = s.type === 'buy' ? 'COMPRA' : 'VENDA';
  document.getElementById('rpTipDate').textContent = String(s.time).replace(' *','');
  document.getElementById('rpTipBody').innerHTML = _buildTipBody(s);
  const rect = chartDiv.getBoundingClientRect();
  const tw = 260;
  const th = rpTip.offsetHeight || 220;
  let L = px + 15; if (L + tw > rect.width - 10) L = px - tw - 15; if (L < 10) L = 10;
  let T = py + 15; if (T + th > rect.height - 10) T = py - th - 15; if (T < 10) T = 10;
  rpTip.style.left = L + 'px';
  rpTip.style.top = T + 'px';
}}

function hideRpTip() {{ rpTip.classList.remove('visible'); }}

chart.subscribeCrosshairMove(param => {{
  if (!param || !param.time || !param.point) {{ hideRpTip(); return; }}
  const s = SIGNALS_BY_TIME[String(param.time)];
  if (s) showRpTip(s, param.point.x, param.point.y); else hideRpTip();
}});

// ── INIT ─────────────────────────────────────────────
document.getElementById('rpSlider').max = N - 1;
document.getElementById('rpSigCount').textContent =
  `${{SIGNALS.filter(s => s.type === 'buy').length}} compres · ${{SIGNALS.filter(s => s.type === 'sell').length}} vendes`;

renderUpTo(Math.min(30, N - 1));

// ── Descàrrega PNG ────────────────────────────────────────────
// Captura del panell principal del replay (preu). Funciona en qualsevol
// moment de la reproducció: el PNG reflecteix l'estat actual del gràfic.
function rpDownloadPng() {{
  try {{
    const canvas = chart.takeScreenshot();
    canvas.toBlob(function(blob) {{
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const ts = new Date().toISOString().slice(0,10);
      link.href = url;
      link.download = 'replay_' + ts + '.png';
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {{
        URL.revokeObjectURL(url);
        link.remove();
      }}, 100);
    }}, 'image/png');
  }} catch (e) {{
    alert('Error generant el PNG: ' + e.message);
  }}
}}

// Resize handler — aplica el nou amplada als 3 panells
new ResizeObserver(() => {{
  const w = W();
  chart.applyOptions({{width: w}});
  volChart.applyOptions({{width: w}});
  atrChart.applyOptions({{width: w}});
}}).observe(chartDiv);
</script>
</body>
</html>"""

