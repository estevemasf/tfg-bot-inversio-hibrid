"""
ui/tab_fiscal.py — Pestanya "Fiscalitat".

Mostra l'impacte fiscal (IRPF, base de l'estalvi) sobre els resultats
de la cartera. Consta de:

  1. Controls editables de l'escala (delegats a fiscal_ui).
  2. KPIs fiscals: rendiment brut vs net, impostos, cost fiscal.
  3. Taula de liquidació exercici per exercici.
  4. Comparativa Estratègia vs Buy & Hold DESPRÉS d'impostos, que és on
     es veu el fenomen del diferiment fiscal.
  5. Nota metodològica per a la memòria del treball.

FONT DE DADES:
Aquesta pestanya NO recalcula cap backtest. Llegeix els resultats que la
pestanya "Backtest" (cartera) ha desat a st.session_state["fiscal_data"].
Si l'usuari encara no ha executat el backtest de cartera, mostra un avís
demanant que ho faci primer. Així s'evita duplicar càlcul pesat.
"""
from __future__ import annotations

import streamlit as st

from core.fiscal import (
    compute_tax_summary,
    apply_tax_to_equity,
    TaxableSale,
)
from core.strategy import build_msci_etf_equity
from core.data_io import load_msci_world
from core.config import INDICES_PATH
from ui.fiscal_ui import (
    render_tax_controls,
    render_tax_kpis,
    render_yearly_tax_table,
    render_scale_reference,
)


def render_fiscalitat() -> None:
    """Renderitza la pestanya Fiscalitat completa."""
    st.markdown(
        "<div style='position:relative;'>"
        "<h2 style='margin-bottom:2px;'>🧾 Fiscalitat de la cartera</h2>"
        "<p style='color:#94a3b8;font-size:.88rem;margin-top:0;'>"
        "Impacte de l'IRPF (base imposable de l'estalvi) sobre els "
        "resultats del backtest. Tots els càlculs es deriven de les "
        "operacions de la pestanya <b>Backtest</b>.</p>"
        "<button onclick='window.print()' class='print-pdf-btn-fiscal' "
        "title='Desa aquesta pestanya com a PDF'>"
        "🖨️&nbsp;Desar com a PDF</button>"
        "<style>"
        ".print-pdf-btn-fiscal{position:absolute;top:0;right:0;"
        "background:#1e293b;color:#f1f5f9;border:1px solid #334155;"
        "border-radius:8px;padding:8px 14px;font-size:.82rem;"
        "font-weight:600;cursor:pointer;font-family:inherit;}"
        ".print-pdf-btn-fiscal:hover{background:#334155;border-color:#60a5fa;}"
        "@media print{.print-pdf-btn-fiscal{display:none!important;}}"
        "</style>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── 1. Controls editables de l'escala ──────────────────────
    with st.container(border=True):
        st.markdown(
            "<div style='font-size:.74rem;color:#94a3b8;font-weight:700;"
            "text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;'>"
            "⚙️ Configuració fiscal</div>",
            unsafe_allow_html=True,
        )
        tax_cfg = render_tax_controls(scope="fiscal", compact=False)

    # ── 1b. Taula de referència de les escales 2014–2025 ───────
    with st.expander("📋 Escala de l'estalvi vigent per exercici (2014–2025)"):
        st.markdown(render_scale_reference(), unsafe_allow_html=True)

    # ── 2. Comprovem que hi hagi dades del backtest ────────────
    # Prioritat: dades de CARTERA (càlcul fiscalment vàlid, base global).
    # Si no n'hi ha, caiem a les dades d'un ACTIU individual (la pestanya
    # Acció les desa). En aquest segon cas s'avisa que el càlcul és
    # orientatiu, perquè la base de l'estalvi real és de cartera.
    fiscal_data = st.session_state.get("fiscal_data")
    is_portfolio = fiscal_data is not None
    if fiscal_data is None:
        fiscal_data = st.session_state.get("fiscal_data_accio")

    if not fiscal_data:
        st.info(
            "ℹ️ Encara no hi ha dades per analitzar. Tens dues opcions:\n\n"
            "• **Recomanat** — ves a la pestanya **Backtest**, executa el "
            "backtest de la cartera sencera, i torna aquí: l'anàlisi fiscal "
            "completa (base de l'estalvi global de tots els actius) es "
            "generarà automàticament.\n\n"
            "• **Alternativa** — ves a la pestanya **Acció individual**, "
            "tria una empresa, i torna aquí: veuràs l'anàlisi fiscal "
            "orientativa d'aquell sol actiu."
        )
        _render_methodology_note()
        return

    if not tax_cfg.enabled:
        st.warning(
            "⚪ La fiscalitat està desactivada. Activa-la al control de "
            "dalt per veure l'anàlisi."
        )
        _render_methodology_note()
        return

    # Avís segons l'origen de les dades
    if is_portfolio:
        st.success(
            f"✓ Analitzant la **cartera completa** "
            f"({len(fiscal_data['assets'])} actius) · període "
            f"{fiscal_data['period'][0]} → {fiscal_data['period'][1]}."
        )
    else:
        st.warning(
            f"⚠️ Mostrant l'anàlisi d'**un sol actiu** "
            f"({fiscal_data['assets'][0]['ticker']}), perquè encara no "
            f"s'ha executat el backtest de cartera. La base de l'estalvi "
            f"real és **de cartera** (suma de tots els valors): per al "
            f"càlcul fiscalment vàlid, executa el backtest a la pestanya "
            f"**Backtest**."
        )

    # ── 3. Recollim totes les vendes de tots els actius ────────
    # fiscal_data["assets"] = [{ticker, trades, equity, bh_equity,
    #                           capital_inicial, capital_final,
    #                           bh_capital_final}, ...]
    all_sales: list[TaxableSale] = []
    bh_sales: list[TaxableSale] = []
    capital_inicial_total = 0.0
    capital_brut_total = 0.0
    bh_brut_total = 0.0

    for asset in fiscal_data["assets"]:
        ticker = asset["ticker"]
        capital_inicial_total += asset["capital_inicial"]
        capital_brut_total += asset["capital_final"]
        bh_brut_total += asset["bh_capital_final"]

        # Vendes de l'ESTRATÈGIA: una per operació tancada
        for t in asset["trades"]:
            try:
                from core.fiscal import _to_date
                buy_d = _to_date(t["Entrada"])
                sell_d = _to_date(t["Sortida"])
            except Exception:
                continue
            all_sales.append(TaxableSale(
                ticker=ticker, sell_date=sell_d, buy_date=buy_d,
                pnl=float(t.get("Guany/Perdua", 0.0)),
            ))

        # Venda del BUY & HOLD: una única transmissió al final del període.
        # El guany del B&H és (capital final B&H − capital inicial).
        bh_pnl = asset["bh_capital_final"] - asset["capital_inicial"]
        bh_dates = asset.get("period", None)
        if bh_dates:
            from core.fiscal import _to_date
            try:
                bh_sales.append(TaxableSale(
                    ticker=ticker,
                    sell_date=_to_date(bh_dates[1]),
                    buy_date=_to_date(bh_dates[0]),
                    pnl=bh_pnl,
                ))
            except Exception:
                pass

    # ── 4. Liquidació fiscal ───────────────────────────────────
    summ_strat = compute_tax_summary(all_sales, tax_cfg)
    summ_bh = compute_tax_summary(bh_sales, tax_cfg)

    capital_net_total = capital_brut_total - summ_strat.total_tax
    bh_net_total = bh_brut_total - summ_bh.total_tax

    # ── 5. KPIs fiscals de l'estratègia ────────────────────────
    st.markdown(
        "<div style='font-size:.8rem;color:#cbd5e1;font-weight:700;"
        "margin:16px 0 4px;'>📊 Impacte fiscal sobre l'estratègia</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        render_tax_kpis(
            capital_brut=capital_brut_total,
            capital_net=capital_net_total,
            total_tax=summ_strat.total_tax,
            total_disallowed=summ_strat.total_losses_disallowed,
            capital_inicial=capital_inicial_total,
        ),
        unsafe_allow_html=True,
    )

    # ── 6. Taula de liquidació anual ───────────────────────────
    st.markdown(
        "<div style='font-size:.8rem;color:#cbd5e1;font-weight:700;"
        "margin:14px 0 4px;'>📅 Liquidació exercici per exercici "
        "(estratègia)</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        render_yearly_tax_table(summ_strat.yearly),
        unsafe_allow_html=True,
    )

    # ── 7. MSCI World tractat com a ETF amb costos i IRPF ─────
    # Per oferir una comparativa de 3 vies (Estratègia / B&H / MSCI),
    # carreguem el MSCI World i li apliquem el mateix tractament que al
    # B&H: 1 compra + 1 venda + TER anual + IRPF a la venda final. Així
    # la comparació amb el benchmark és simètrica.
    #
    # Els paràmetres de costos els recuperem de st.session_state (els
    # ha configurat l'usuari a la pestanya Backtest o Acció). Si no
    # existeixen, fem servir els defectes (0.25% fee, 0.20% TER).
    msci_brut_total = 0.0
    msci_net_total = 0.0
    msci_total_tax = 0.0
    msci_available = False
    try:
        msci_df_global = load_msci_world(INDICES_PATH)
        if msci_df_global is not None and not msci_df_global.empty:
            period = fiscal_data.get("period", None)
            if period:
                from datetime import date as _dt
                d_from = _dt.fromisoformat(period[0][:10])
                d_to = _dt.fromisoformat(period[1][:10])
                msci_local = msci_df_global[
                    (msci_df_global["Date"].dt.date >= d_from) &
                    (msci_df_global["Date"].dt.date <= d_to)
                ].copy().reset_index(drop=True)
                if not msci_local.empty:
                    # Paràmetres de costos: usem la sessió del backtest
                    # (la pestanya Fiscalitat no té sliders propis).
                    fee_pct_used = float(
                        st.session_state.get("fee_pct_pf",
                            st.session_state.get("fee_pct_single", 0.25))
                    ) / 100.0
                    ter_pct_used = float(
                        st.session_state.get("msci_ter_pf",
                            st.session_state.get("msci_ter_single", 0.20))
                    ) / 100.0
                    msci_result = build_msci_etf_equity(
                        msci_local,
                        capital_inicial=float(capital_inicial_total),
                        fee_pct=fee_pct_used,
                        slippage_buy_pct=0.0,
                        slippage_sell_pct=0.0,
                        ter_annual_pct=ter_pct_used,
                    )
                    msci_brut_total = float(msci_result["capital_final"])

                    # Fiscalitat MSCI: 1 sola venda al final del període
                    msci_pnl = msci_brut_total - float(capital_inicial_total)
                    from core.fiscal import _to_date as _td
                    msci_sales = [TaxableSale(
                        ticker="MSCI_WORLD",
                        sell_date=_td(period[1]),
                        buy_date=_td(period[0]),
                        pnl=msci_pnl,
                    )]
                    msci_summ = compute_tax_summary(msci_sales, tax_cfg)
                    msci_total_tax = msci_summ.total_tax
                    msci_net_total = msci_brut_total - msci_total_tax
                    msci_available = True
    except Exception:
        # Si falla la càrrega o el càlcul, simplement no es mostra el MSCI
        # a la comparativa. No volem que un error opcional petis tota la
        # pestanya.
        msci_available = False

    # ── 8. Comparativa Estratègia vs B&H (vs MSCI) després d'impostos ──
    _render_after_tax_comparison(
        capital_inicial_total,
        capital_brut_total, capital_net_total, summ_strat.total_tax,
        bh_brut_total, bh_net_total, summ_bh.total_tax,
        msci_brut=msci_brut_total if msci_available else None,
        msci_net=msci_net_total if msci_available else None,
        msci_tax=msci_total_tax if msci_available else None,
    )

    # ── 9. Nota metodològica ───────────────────────────────────
    _render_methodology_note()


def _render_after_tax_comparison(
    cap_init: float,
    strat_brut: float, strat_net: float, strat_tax: float,
    bh_brut: float, bh_net: float, bh_tax: float,
    msci_brut: float | None = None,
    msci_net: float | None = None,
    msci_tax: float | None = None,
) -> None:
    """Taula comparativa de 3 vies abans/després d'impostos.

    És la secció amb més valor acadèmic: visualitza el fenomen del
    diferiment fiscal entre tres alternatives d'inversió:
      • Estratègia activa → tributa cada any que tanca posicions amb guany
      • Buy & Hold de la cartera → tributa una sola vegada al final
      • Benchmark MSCI World (ETF) → també tributa una sola vegada al final

    El B&H i el MSCI gaudeixen del diferiment fiscal complet; l'estratègia
    activa no. La diferència entre l'avantatge BRUT i NET de l'estratègia
    quantifica el cost d'aquesta liquidació anticipada.

    Args:
        cap_init: capital inicial de la cartera (€).
        strat_brut/net/tax: capital final brut, net i impost de l'estratègia.
        bh_brut/net/tax: ídem per al Buy & Hold.
        msci_brut/net/tax: ídem per al MSCI World (opcional). Si és None,
            la fila i les targetes corresponents s'amaguen (cas que el CSV
            del MSCI no estigui disponible).
    """
    def _pct(cap):
        return (cap / cap_init - 1.0) * 100.0 if cap_init else 0.0

    # Avantatges (l'estratègia vs cada benchmark)
    adv_brut_bh = _pct(strat_brut) - _pct(bh_brut)
    adv_net_bh = _pct(strat_net) - _pct(bh_net)
    has_msci = msci_brut is not None and msci_net is not None and msci_tax is not None
    if has_msci:
        adv_brut_msci = _pct(strat_brut) - _pct(msci_brut)
        adv_net_msci = _pct(strat_net) - _pct(msci_net)

    st.markdown(
        "<div style='font-size:.8rem;color:#cbd5e1;font-weight:700;"
        "margin:18px 0 4px;'>⚖️ Estratègia vs Buy &amp; Hold vs MSCI World"
        " — abans i després d'impostos</div>",
        unsafe_allow_html=True,
    )

    def _row(label, brut, net, tax, color, bg):
        return (
            f'<tr style="background:{bg};border-bottom:1px solid #1e293b;">'
            f'<td style="padding:11px 14px;font-weight:700;color:{color};">{label}</td>'
            f'<td style="padding:11px 14px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;color:#f1f5f9;font-weight:600;">'
            f'{_pct(brut):+.2f}%</td>'
            f'<td style="padding:11px 14px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;color:#fbbf24;font-weight:600;">{tax:,.2f}€</td>'
            f'<td style="padding:11px 14px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;font-weight:700;color:#f1f5f9;">'
            f'{_pct(net):+.2f}%</td>'
            f'</tr>'
        )

    rows_html = (
        _row("📈 Estratègia", strat_brut, strat_net, strat_tax,
             "#10b981", "#0f172a")
        + _row("📊 Buy &amp; Hold", bh_brut, bh_net, bh_tax,
               "#3b82f6", "#0a0a0a")
    )
    if has_msci:
        rows_html += _row(
            "🌍 MSCI World (ETF)", msci_brut, msci_net, msci_tax,
            "#f59e0b", "#0f172a",
        )

    table = f"""
    <div style="overflow-x:auto;border:1px solid #2a2a2a;border-radius:12px;
                background:#0a0a0a;">
    <table style="width:100%;border-collapse:collapse;font-size:.85rem;">
      <thead>
        <tr style="background:#0a0a0a;border-bottom:1px solid #2a2a2a;
                   color:#94a3b8;font-size:.66rem;text-transform:uppercase;
                   letter-spacing:.04em;font-weight:700;">
          <th style="padding:11px 14px;text-align:left;">Cartera</th>
          <th style="padding:11px 14px;text-align:right;">Rendiment brut</th>
          <th style="padding:11px 14px;text-align:right;">Impostos</th>
          <th style="padding:11px 14px;text-align:right;">Rendiment net</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table></div>"""
    st.markdown(table, unsafe_allow_html=True)

    # ── Targetes amb avantatges (vs B&H i vs MSCI) ──
    def _adv_card(title, value, color, subtitle=""):
        sub_html = (
            f'<div style="font-size:.66rem;color:#94a3b8;margin-top:4px;">'
            f'{subtitle}</div>'
            if subtitle else ""
        )
        return (
            f'<div style="flex:1;min-width:180px;background:#111111;'
            f'border:1px solid #2a2a2a;border-radius:12px;padding:12px 15px;">'
            f'<div style="font-size:.66rem;color:#94a3b8;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:.05em;">{title}</div>'
            f'<div style="font-family:\'DM Mono\',monospace;font-size:1.05rem;'
            f'font-weight:700;color:{color};margin-top:3px;">{value}</div>'
            f'{sub_html}</div>'
        )

    cards = []
    cards.append(_adv_card(
        "Avantatge vs B&H — BRUT", f"{adv_brut_bh:+.2f} pp",
        "#16a34a" if adv_brut_bh >= 0 else "#dc2626",
        subtitle="Estratègia vs Buy & Hold cartera",
    ))
    cards.append(_adv_card(
        "Avantatge vs B&H — NET", f"{adv_net_bh:+.2f} pp",
        "#16a34a" if adv_net_bh >= 0 else "#dc2626",
        subtitle="Després d'IRPF",
    ))
    if has_msci:
        cards.append(_adv_card(
            "Avantatge vs MSCI — BRUT", f"{adv_brut_msci:+.2f} pp",
            "#16a34a" if adv_brut_msci >= 0 else "#dc2626",
            subtitle="Estratègia vs benchmark global",
        ))
        cards.append(_adv_card(
            "Avantatge vs MSCI — NET", f"{adv_net_msci:+.2f} pp",
            "#16a34a" if adv_net_msci >= 0 else "#dc2626",
            subtitle="Després d'IRPF",
        ))

    st.markdown(
        '<div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap;">'
        + "".join(cards)
        + '</div>',
        unsafe_allow_html=True,
    )

    # Interpretació automàtica — basada en B&H (el cas central)
    delta_adv = adv_net_bh - adv_brut_bh
    if delta_adv < -0.01:
        msg = (
            f"📉 La fiscalitat <b>redueix</b> l'avantatge de l'estratègia "
            f"vs Buy &amp; Hold en {abs(delta_adv):.2f} pp. És l'efecte "
            f"esperat del <b>diferiment fiscal</b>: el B&amp;H i el MSCI "
            f"World ajornen tota la tributació al final del període, "
            f"mentre que l'estratègia activa tributa cada any que realitza "
            f"guanys. El benchmark global (MSCI), a més, és un punt de "
            f"referència del que un inversor passiu hauria pogut obtenir."
        )
    elif delta_adv > 0.01:
        msg = (
            f"📈 La fiscalitat <b>amplia</b> l'avantatge de l'estratègia "
            f"en {delta_adv:.2f} pp. Això passa quan el Buy &amp; Hold "
            f"concentra tant de guany en un sol exercici que salta a "
            f"trams superiors de l'escala progressiva, pagant un tipus "
            f"efectiu més alt que l'estratègia."
        )
    else:
        msg = "La fiscalitat té un efecte gairebé neutre sobre l'avantatge relatiu."

    st.markdown(
        f"<div style='background:#0f172a;border-left:3px solid #0ea5e9;"
        f"padding:10px 14px;border-radius:6px;margin-top:10px;font-size:.82rem;"
        f"color:#cbd5e1;'>{msg}</div>",
        unsafe_allow_html=True,
    )


def _render_methodology_note() -> None:
    """Nota metodològica fixa, útil tant per l'usuari com per a la memòria."""
    with st.expander("📖 Metodologia fiscal i base normativa"):
        st.markdown(
            """
**Marc legal.** Es modela la tributació de guanys i pèrdues patrimonials
per transmissió de valors dins la **base imposable de l'estalvi** de
l'IRPF (Ley 35/2006).

**Escala vigent per exercici.** El model NO aplica una escala única a
tot el període: cada exercici tributa amb l'escala **realment vigent**
aquell any. Així, una plusvàlua de 2016 tributa amb la normativa de
2016, no amb la de 2025. Evolució: 2014 → 21/25/27 %; 2015 → 20/22/24 %
(any de transició de la reforma); 2016–2020 → 19/21/23 %; 2021–2022 →
s'afegeix el tram del 26 %; 2023–2024 → 19/21/23/27/28 %; 2025 → el
darrer tram puja al 30 % (Ley 7/2024). Aquest enfocament evita la
crítica d'aplicar tipus actuals retroactivament. Opcionalment, el bot
permet el mode "escala fixa" per a anàlisi de sensibilitat.

**Liquidació anual.** Cada exercici és un fet imposable independent. Els
guanys per venda de valors **no es retenen a l'origen**: el contribuent
els autoliquida a la declaració de l'IRPF de l'any següent. El backtest
reflecteix aquesta liquidació anual.

**Regla dels 2 mesos** (art. 33.5.f LIRPF). Una pèrdua no es computa si
es recompra el mateix valor dins de ±2 mesos; queda diferida.

**Compensació de pèrdues.** Les pèrdues compensen guanys de l'exercici;
el sobrant s'arrossega fins a 4 exercicis.

**Diferiment fiscal.** El Buy & Hold tributa una única vegada al final
del període; l'estratègia activa tributa cada any. Aquesta diferència
temporal afecta el rendiment net i és l'objecte central d'aquesta
pestanya.

**Simplificacions assumides.** S'assumeix resident fiscal a Espanya tot
el període i operacions amb accions cotitzades integrades a la base de
l'estalvi. No es modelen dividends ni les seves retencions, retencions
internacionals, convenis de doble imposició, canvis de residència
fiscal, obligacions informatives de bròquers estrangers ni compensació
creuada amb rendiments del capital mobiliari. L'impost de l'exercici es
descompta del capital el 31/12 (a la realitat es pagaria el juny
següent). FIFO es respecta de manera trivial perquè la cartera tanca
posicions senceres.
            """
        )
