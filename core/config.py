"""
Configuració global del bot TFG: paths, columnes i StrategyConfig.
Aquest mòdul NO té dependències de Streamlit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# RUTES (ajusta a la teva màquina)
# ─────────────────────────────────────────────────────────────
HISTORICAL_PATH = Path("historical_ohlc_top30")
INDICES_PATH = Path(r"historical_ohlc_indices")
LOGOS_PATH = Path(r"logos")
MSCI_WORLD_FILENAME = "MSCI_WORLD_2014_today.csv"


# ─────────────────────────────────────────────────────────────
# PERÍODE D'ESTUDI (TFG) + WARM-UP D'INDICADORS
# ─────────────────────────────────────────────────────────────
# Període que es vol analitzar al treball. Els selectors de data de la
# UI s'inicialitzen amb aquests valors (clampats al rang disponible de
# cada actiu).
#
# Garantia que s'aplica al backtest:
#   • Cap COMPRA es pot executar abans de STUDY_START_DATE.
#   • Cap COMPRA es pot executar després de STUDY_END_DATE.
#   • Si queda una posició oberta al final del període, es força la
#     venda al tancament del darrer dia (forced_close_eop).
#   • Totes les mètriques (Sharpe, CAGR, drawdown, B&H, equity curve)
#     es calculen exclusivament sobre [STUDY_START_DATE, STUDY_END_DATE].
STUDY_START_DATE: date = date(2015, 1, 1)
STUDY_END_DATE:   date = date(2025, 12, 31)

# Dies naturals ABANS de la data inicial seleccionada que es carreguen
# únicament per "escalfar" els indicadors (DSVWAP amb ds_prd=55,
# ATR(14), Reversal Entry Zones). Aquestes dades de warm-up NO generen
# cap operació: només s'usen per estabilitzar les fórmules dels
# indicadors abans que arrenqui el període d'estudi.
#
# Sense warm-up, els primers ~55 dies de borsa del període tenen un
# DSVWAP no convergit i el bot perd ≈2,5 mesos d'operativa al
# començament. Amb 365 dies (un any natural) qualsevol combinació de
# paràmetres del sistema arriba ja estabilitzada al primer dia d'estudi.
#
# Si l'actiu té menys d'1 any de dades anteriors a STUDY_START_DATE
# disponibles, el warm-up s'escurça automàticament al màxim que hi hagi
# (no genera cap error).
WARMUP_BUFFER_DAYS: int = 365


# ─────────────────────────────────────────────────────────────
# COLUMNES DELS CSV DE FONAMENTALS
# ─────────────────────────────────────────────────────────────
FUNDAMENTALS_COLUMNS = [
    "Ticker", "Companyia", "Sector", "Indústria", "Continent", "Pais",
    "Moneda", "Valor de mercat", "Benefici Net", "Patrimoni Net",
    "EPS_t", "EPS_(t-1)", "Cash Flow Operatiu", "CAPEX", "Benefici Operatiu",
    "Ingressos", "Deute total", "EBITDA", "Actiu Corrent", "Passiu Corrent",
    "Cash + Short Term Investments", "Enterprise Value", "Preu", "Ticker Yahoo",
]

COMMON_INDICATORS_COLUMNS = [
    "Ticker", "Companyia", "ROIC (20%)", "Net Margin (10%)",
    "Operating Margin (10%)", "Current Ratio (10%)", "PER (10%)",
]

INDUSTRIAL_INDICATORS_COLUMNS = [
    "Ticker", "Companyia", "EPS Growth (10%)", "FCF Yield (10%)",
    "Debt/EBITDA (10%)", "EV/EBITDA (10%)",
]

FINANCIAL_INDICATORS_COLUMNS = [
    "Ticker", "Companyia", "EPS Growth (10%)", "Debt/Equity (20%)", "P/B (10%)",
]


# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓ DE L'ESTRATÈGIA (Reversal + DSVWAP)
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StrategyConfig:
    # ── Reversal Entry Zones ────────────────────────────
    reversal_confirm_bars: int = 0
    reversal_preset: str = "Low"          # "Low" / "Very Low"
    reversal_calc_mode: str = "Average"   # "Average" / "High/Low"
    reversal_avg_len: int = 5
    reversal_atr_len: int = 5
    reversal_custom_abs: float = 0.05

    # ── Dynamic Swing VWAP ──────────────────────────────
    ds_prd: int = 55
    ds_base_apt: float = 21.0
    ds_use_adapt: bool = False
    ds_vol_bias: float = 10.0
    ds_src: str = "hlc3"                  # "hlc3" / "ohlc4" / "close" / "hl2"
    ds_vol_cap: bool = True
    ds_smooth_anchor: bool = True
    ds_only_llhh: bool = False
    ds_band_mult: float = 0.618

    # ── (POSITION SIZING ELIMINAT) ──────────────────────────
    # El sistema sempre inverteix el 100% del capital disponible a cada compra,
    # comprant el màxim nombre d'accions enteres possibles. No hi ha
    # apalancament ni deute en cap forma.

    # ── Execució diferida (REGLA PRINCIPAL DEL SISTEMA) ──
    # La senyal diària queda assignada a la data de la barra, però només és
    # definitiva al tancament. Per tant, la versió realista (i defecte) és delay=1.
    #   0 = [optimista/comparatiu] close del mateix dia → pot amagar look-ahead
    #   1 = [REALISTA / DEFECTE] close del dia següent → elimina look-ahead
    #   2 = [conservador] close del dia+2 → més confirmació, menys reactiu
    entry_delay_bars: int = 1

    # ── Costos de transacció (percentuals sobre el preu) ──
    # Fee = comissió del broker · Slippage = desviació del preu vs mid
    # COMPRA executada a:  Close × (1 + slippage_buy_pct)  més una comissió del fee_buy_pct
    # VENDA  executada a:  Close × (1 - slippage_sell_pct) menys una comissió del fee_sell_pct
    fee_buy_pct: float = 0.0              # p.ex. 0.001 = 0.1%
    fee_sell_pct: float = 0.0
    slippage_buy_pct: float = 0.0         # p.ex. 0.0005 = 5 basis points
    slippage_sell_pct: float = 0.0

    # ── Cost de manteniment/custòdia del Buy & Hold ──────
    # Taxa ANUAL aplicada al valor mantingut de la posició B&H, prorratejada
    # per dies. Quan es compara l'estratègia contra el B&H, aquest cost
    # s'aplica al B&H; per a l'estratègia, la comissió per operació ja hi és.
    bh_annual_maintenance_pct: float = 0.0  # p.ex. 0.002 = 0.2% anual

    # ── TER (Total Expense Ratio) del MSCI World ────────
    # Quan es compara amb el MSCI World com a benchmark, es modela una
    # inversió en un ETF que rèplica l'índex (p.ex. iShares Core MSCI
    # World, Vanguard FTSE Developed World). Aquest tipus d'ETF cobra una
    # despesa anual de gestió (Total Expense Ratio) que erosiona la
    # rendibilitat. Es prorrateja per dies, igual que el manteniment B&H.
    # Valor per defecte: 0.20% (típic d'ETFs grans i líquids del MSCI).
    msci_ter_annual_pct: float = 0.002  # 0.2% anual

    # ── Stops opcionals (desactivats per defecte) ──
    # stop_loss_atr_mult: si el preu cau per sota de entry_price − N×ATR(14)_entrada,
    #                     es tanca la posició al Close d'aquesta barra.
    # trailing_stop_atr_mult: segueix al màxim preu intracompra; si cau més de
    #                         N×ATR per sota del màxim, es tanca.
    # None = desactivat
    stop_loss_atr_mult: float | None = None
    trailing_stop_atr_mult: float | None = None

    # ── Execució ────────────────────────────────────────
    capital_inicial: float = 10_000.0


DEFAULT_CFG = StrategyConfig()


# Etiquetes dels modes d'execució (reutilitzables a la UI i testos)
EXEC_MODE_LABELS = {
    0: "Optimista (comparatiu)",
    1: "Realista (defecte)",
    2: "Conservador",
}
