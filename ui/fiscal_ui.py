"""
ui/fiscal_ui.py — Components d'interfície per a la fiscalitat.

Capa Streamlit del mòdul fiscal. Conté:

  • render_tax_controls(scope) — controls editables (mode d'escala, regla
                               dels 2 mesos, llindar exempt). El paràmetre
                               `scope` és OBLIGATORI: identifica quina
                               pestanya invoca els controls i evita
                               col·lisió de claus de widget.
  • tax_config_from_state()    — construeix un TaxConfig a partir de
                               l'estat canònic compartit.
  • render_yearly_tax_table()  — taula HTML de la liquidació any per any.
  • render_tax_kpis()          — fila de KPIs fiscals.
  • render_scale_reference()   — taula de referència 2014–2025.

═══════════════════════════════════════════════════════════════════════
ARQUITECTURA DE L'ESTAT (compartit entre 3 pestanyes)
═══════════════════════════════════════════════════════════════════════
render_tax_controls() es crida des de TRES pestanyes: Acció, Cartera i
Fiscalitat. Streamlit prohibeix que dos widgets tinguin la mateixa clau
al mateix render, així que cada instància de control rep claus úniques
amb sufix `_<scope>` (p.ex. `tax_enabled__fiscal`, `tax_enabled__accio`).

Però conceptualment l'usuari espera UNA configuració global: si activa
la fiscalitat des d'Acció, ho ha de veure des de Cartera. Per això hi
ha dues capes:

  ESTAT CANÒNIC (claus sense sufix, font de veritat):
      tax_enabled, tax_mode, tax_apply_2m, tax_exempt, tax_fixrate_0..4

  ESTAT DE WIDGET (claus amb sufix, només per evitar col·lisions):
      tax_enabled__fiscal, tax_enabled__accio, tax_enabled__cartera, ...

El flux a cada render és:
  1) _init_tax_state() inicialitza l'estat canònic si no existeix i
     processa una eventual petició de reset.
  2) _sync_widget_keys_from_canonical(scope) copia els valors canònics
     a les claus de widget d'aquest scope (perquè el widget mostri el
     valor compartit, no el que tenia abans en aquest scope).
  3) Es dibuixen els widgets amb claus `<canonical>__<scope>`.
  4) _sync_canonical_from_widget_keys(scope) copia el que ha quedat als
     widgets cap a les claus canòniques (perquè el canvi es propagui a
     les altres pestanyes a la propera visita).
"""
from __future__ import annotations

import streamlit as st

from core.fiscal import (
    TaxBracket,
    TaxConfig,
    SPAIN_SAVINGS_BRACKETS_2025,
    SPAIN_SAVINGS_BRACKETS_BY_YEAR,
    YearlyTaxResult,
    brackets_for_year,
    _scale_label,
)


# Claus de l'estat CANÒNIC (sense sufix). Són les que llegeix la resta
# de l'app via tax_config_from_state().
_CANON_BOOL_KEYS = ["tax_enabled", "tax_apply_2m"]
_CANON_STR_KEYS = ["tax_mode"]
_CANON_FLOAT_KEYS = ["tax_exempt"]  # + tax_fixrate_0..4 dinàmics

# Modes vàlids del radio
_MODE_PER_YEAR = "Per exercici fiscal (recomanat)"
_MODE_FIXED = "Escala fixa per a tot el període"


def _scoped(key: str, scope: str) -> str:
    """Genera la clau de widget per a un scope concret.

    Ex: _scoped("tax_enabled", "fiscal") → "tax_enabled__fiscal"
    """
    return f"{key}__{scope}"


# ─────────────────────────────────────────────────────────────
# INICIALITZACIÓ I RESET DE L'ESTAT CANÒNIC
# ─────────────────────────────────────────────────────────────
def _init_tax_state() -> None:
    """Inicialitza l'estat canònic i processa una petició de reset PENDENT.

    Es crida al principi de render_tax_controls, ABANS de cap widget. El
    botó de reset (que viu només a la pestanya Fiscalitat) no escriu mai
    a les claus de widget directament: només marca `tax_reset_pending`,
    fa rerun, i aquí es restauren els valors abans que es creïn widgets
    nous (Streamlit prohibeix modificar la clau d'un widget instanciat).
    """
    fixed_rates = [b.rate for b in SPAIN_SAVINGS_BRACKETS_2025]

    # 1) Processem una petició de reset pendent
    if st.session_state.get("tax_reset_pending", False):
        st.session_state["tax_mode"] = _MODE_PER_YEAR
        st.session_state["tax_apply_2m"] = True
        st.session_state["tax_exempt"] = 0.0
        for i, rate in enumerate(fixed_rates):
            st.session_state[f"tax_fixrate_{i}"] = rate * 100.0
        st.session_state["tax_reset_pending"] = False
        # Notem totes les claus de widget de tots els scopes coneguts per
        # forçar que la propera sincronització de widget les sobreescrigui.
        # No cal: la sincronització ho farà igualment.

    # 2) Defaults de l'estat canònic (només la primera vegada)
    if "tax_enabled" not in st.session_state:
        st.session_state["tax_enabled"] = True
    if "tax_mode" not in st.session_state:
        st.session_state["tax_mode"] = _MODE_PER_YEAR
    if "tax_apply_2m" not in st.session_state:
        st.session_state["tax_apply_2m"] = True
    if "tax_exempt" not in st.session_state:
        st.session_state["tax_exempt"] = 0.0
    for i, rate in enumerate(fixed_rates):
        if f"tax_fixrate_{i}" not in st.session_state:
            st.session_state[f"tax_fixrate_{i}"] = rate * 100.0


def _sync_widget_keys_from_canonical(scope: str, full: bool) -> None:
    """Copia l'estat CANÒNIC a les claus de widget d'aquest scope.

    Es crida JUST ABANS de dibuixar els widgets, perquè cada widget
    mostri el valor canònic (el que s'ha pogut canviar des d'una altra
    pestanya). `full` indica si cal sincronitzar també els controls que
    només apareixen en mode no-compact (mode i fixrates).
    """
    n_fix = len(SPAIN_SAVINGS_BRACKETS_2025)
    keys = ["tax_enabled", "tax_apply_2m", "tax_exempt"]
    if full:
        keys += ["tax_mode"] + [f"tax_fixrate_{i}" for i in range(n_fix)]
    for k in keys:
        st.session_state[_scoped(k, scope)] = st.session_state[k]


def _sync_canonical_from_widget_keys(scope: str, full: bool) -> None:
    """Copia el que han quedat als widgets cap a les claus CANÒNIQUES.

    Es crida JUST DESPRÉS de dibuixar els widgets, perquè qualsevol
    interacció de l'usuari en aquest scope es propagui a les altres
    pestanyes al proper render.
    """
    n_fix = len(SPAIN_SAVINGS_BRACKETS_2025)
    keys = ["tax_enabled", "tax_apply_2m", "tax_exempt"]
    if full:
        keys += ["tax_mode"] + [f"tax_fixrate_{i}" for i in range(n_fix)]
    for k in keys:
        wk = _scoped(k, scope)
        if wk in st.session_state:
            st.session_state[k] = st.session_state[wk]


# ─────────────────────────────────────────────────────────────
# CONSTRUCCIÓ DEL TaxConfig DES DE L'ESTAT CANÒNIC
# ─────────────────────────────────────────────────────────────
def tax_config_from_state() -> TaxConfig:
    """Construeix un TaxConfig llegint l'estat CANÒNIC.

    Aquesta funció és la ÚNICA via per obtenir la configuració fiscal,
    de manera que tot el bot vegi la mateixa configuració. NO mira les
    claus de widget amb sufix.
    """
    # Garanteix que les claus existeixen (per si es crida abans que cap
    # render_tax_controls hagi corregut).
    _init_tax_state()

    enabled = st.session_state.get("tax_enabled", True)
    mode = st.session_state.get("tax_mode", _MODE_PER_YEAR)
    apply_2m = st.session_state.get("tax_apply_2m", True)
    exempt = float(st.session_state.get("tax_exempt", 0.0))

    per_year = mode.startswith("Per exercici")

    limits = [b.up_to for b in SPAIN_SAVINGS_BRACKETS_2025]
    default_rates = [b.rate for b in SPAIN_SAVINGS_BRACKETS_2025]
    fix_rates = [
        float(st.session_state.get(f"tax_fixrate_{i}", default_rates[i] * 100)) / 100.0
        for i in range(len(default_rates))
    ]
    fixed_brackets = tuple(
        TaxBracket(up_to=limits[i], rate=fix_rates[i])
        for i in range(len(fix_rates))
    )

    return TaxConfig(
        enabled=bool(enabled),
        brackets=fixed_brackets,
        apply_two_month_rule=bool(apply_2m),
        loss_carryforward_years=4,
        exempt_threshold=exempt,
        per_year_scale=per_year,
        brackets_by_year=None,
    )


# ─────────────────────────────────────────────────────────────
# CONTROLS EDITABLES
# ─────────────────────────────────────────────────────────────
def render_tax_controls(scope: str, compact: bool = False) -> TaxConfig:
    """Dibuixa els controls fiscals i retorna el TaxConfig resultant.

    Args:
        scope: identificador únic de la pestanya que invoca els controls
            ("fiscal", "accio", "cartera"). S'usa per construir claus de
            widget úniques i evitar StreamlitDuplicateElementKey.
        compact: si True, versió reduïda (per Acció i Cartera). Si False,
            versió completa amb selector de mode i escala fixa editable
            (per la pestanya Fiscalitat).

    Returns:
        TaxConfig amb la configuració triada per l'usuari (llegida de
        l'estat canònic compartit entre pestanyes).
    """
    full = not compact

    # 1) Inicialització i reset eventual de l'estat canònic
    _init_tax_state()

    # 2) Sincronitzem canònic → claus de widget d'aquest scope ABANS de
    #    crear els widgets, perquè reflecteixin canvis fets en altres
    #    pestanyes.
    _sync_widget_keys_from_canonical(scope, full=full)

    # ── Interruptor principal ───────────────────────────
    st.checkbox(
        "Aplicar fiscalitat (IRPF · base de l'estalvi)",
        key=_scoped("tax_enabled", scope),
        help="Si es desactiva, tots els càlculs es mostren BRUTS "
             "(abans d'impostos). Si s'activa, els KPIs i les corbes "
             "reflecteixen el capital NET d'impostos.",
    )

    enabled_now = st.session_state.get(_scoped("tax_enabled", scope), True)

    if not enabled_now:
        st.caption("⚪ Fiscalitat desactivada — els resultats es mostren bruts.")
        _sync_canonical_from_widget_keys(scope, full=full)
        return tax_config_from_state()

    if compact:
        # Versió reduïda per Acció / Cartera
        c1, c2 = st.columns([1, 1])
        with c1:
            st.checkbox(
                "Regla dels 2 mesos",
                key=_scoped("tax_apply_2m", scope),
                help="Bloqueja el còmput de pèrdues si es recompra el "
                     "mateix valor dins de ±2 mesos (art. 33.5.f LIRPF).",
            )
        with c2:
            st.number_input(
                "Llindar exempt anual (€)",
                min_value=0.0, max_value=50_000.0,
                step=500.0, key=_scoped("tax_exempt", scope),
                help="Mínim de la base de l'estalvi exempt. La normativa "
                     "NO en preveu cap per a valors; deixa'l a 0 per al "
                     "càlcul realista.",
            )
        mode = st.session_state.get("tax_mode", "")
        mode_txt = ("escala vigent de cada exercici" if mode.startswith("Per exercici")
                    else "escala fixa")
        st.caption(
            f"ℹ️ Mode actual: **{mode_txt}**. Per canviar el mode o editar "
            f"els trams, ves a la pestanya **Fiscalitat**."
        )
        _sync_canonical_from_widget_keys(scope, full=full)
        return tax_config_from_state()

    # ── Versió completa (pestanya Fiscalitat) ───────────
    st.radio(
        "Mode d'aplicació de l'escala fiscal:",
        options=[_MODE_PER_YEAR, _MODE_FIXED],
        key=_scoped("tax_mode", scope),
        help="• Per exercici: cada any tributa amb l'escala REALMENT "
             "vigent aquell any (2014→2025). És el mode metodològicament "
             "correcte.\n"
             "• Escala fixa: aplica una única escala a tot el període; "
             "útil per a anàlisi de sensibilitat.",
    )

    mode_now = st.session_state.get(_scoped("tax_mode", scope), _MODE_PER_YEAR)
    per_year = mode_now.startswith("Per exercici")

    if per_year:
        st.markdown(
            "<div style='font-size:.78rem;color:#cbd5e1;margin:8px 0 4px;'>"
            "Cada exercici aplica la seva escala vigent. Pots consultar la "
            "taula completa d'escales 2014–2025 a sota.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='font-size:.78rem;color:#cbd5e1;margin:8px 0 4px;'>"
            "Escala única aplicada a TOTS els exercicis. Els <b>tipus</b> "
            "són editables; els <b>límits</b> es mantenen fixos.</div>",
            unsafe_allow_html=True,
        )
        limits = [b.up_to for b in SPAIN_SAVINGS_BRACKETS_2025]
        cols = st.columns(len(limits))
        prev = 0
        labels = []
        for lim in limits:
            if lim is None:
                labels.append(f"> {prev:,.0f} €")
            else:
                labels.append(f"{prev:,.0f}–{lim:,.0f} €")
                prev = int(lim)
        for i, col in enumerate(cols):
            with col:
                st.markdown(
                    f"<div style='font-size:.62rem;color:#94a3b8;font-weight:700;"
                    f"text-transform:uppercase;margin-bottom:2px;'>Tram {i+1}</div>"
                    f"<div style='font-size:.64rem;color:#64748b;margin-bottom:4px;'>"
                    f"{labels[i]}</div>",
                    unsafe_allow_html=True,
                )
                st.number_input(
                    f"Tipus tram {i+1}", min_value=0.0, max_value=60.0,
                    step=0.5, key=_scoped(f"tax_fixrate_{i}", scope),
                    label_visibility="collapsed",
                )

    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 1])
    with c1:
        st.checkbox(
            "Aplicar la regla dels 2 mesos (art. 33.5.f LIRPF)",
            key=_scoped("tax_apply_2m", scope),
            help="Bloqueja el còmput de pèrdues quan es recompra el "
                 "mateix valor dins de ±2 mesos de la venda amb pèrdua.",
        )
    with c2:
        st.number_input(
            "Llindar exempt anual (€)",
            min_value=0.0, max_value=50_000.0,
            step=500.0, key=_scoped("tax_exempt", scope),
            help="Mínim de la base de l'estalvi exempt. La normativa NO "
                 "en preveu cap per a valors; és un paràmetre d'anàlisi "
                 "de sensibilitat. Deixa'l a 0 per al càlcul realista.",
        )

    # El botó de reset NO escriu directament a les claus de widget; només
    # marca una bandera que _init_tax_state processarà al proper render.
    if st.button("↺ Restaurar valors per defecte",
                 key=_scoped("tax_reset", scope)):
        st.session_state["tax_reset_pending"] = True
        st.rerun()

    # 4) Sincronitzem widget → canònic perquè els canvis es vegin a
    #    altres pestanyes al proper render.
    _sync_canonical_from_widget_keys(scope, full=full)

    return tax_config_from_state()


# ─────────────────────────────────────────────────────────────
# RENDER: TAULA DE REFERÈNCIA DE LES ESCALES 2014–2025
# ─────────────────────────────────────────────────────────────
def render_scale_reference() -> str:
    """Genera l'HTML d'una taula amb l'escala de l'estalvi de cada any.

    Disseny en mode fosc per a consistència amb la resta del bot.
    """
    rows = ""
    for yr in range(2014, 2026):
        br = brackets_for_year(yr)
        parts = []
        prev = 0
        for b in br:
            if b.up_to is None:
                parts.append(f"&gt;{prev:,.0f}€: <b>{b.rate*100:g}%</b>")
            else:
                parts.append(f"{prev:,.0f}–{b.up_to:,.0f}€: <b>{b.rate*100:g}%</b>")
                prev = int(b.up_to)
        desc = " · ".join(parts)
        is_change = yr in SPAIN_SAVINGS_BRACKETS_BY_YEAR
        # Anys de canvi normatiu: ressaltats amb un to més càlid
        bg = "#1f1610" if is_change else "#0f172a"
        marker = (
            ' <span style="color:#fbbf24;font-size:.68rem;font-weight:600;">'
            '▲ canvi normatiu</span>'
            if is_change else ""
        )
        rows += (
            f'<tr style="background:{bg};border-bottom:1px solid #1e293b;">'
            f'<td style="padding:8px 12px;color:#f1f5f9;font-weight:700;">'
            f'{yr}{marker}</td>'
            f'<td style="padding:8px 12px;font-size:.8rem;color:#cbd5e1;">'
            f'{desc}</td>'
            f'</tr>'
        )

    return f"""
    <div style="overflow-x:auto;border:1px solid #2a2a2a;border-radius:10px;
                background:#0a0a0a;">
    <table style="width:100%;border-collapse:collapse;font-size:.82rem;">
      <thead>
        <tr style="background:#0a0a0a;border-bottom:1px solid #2a2a2a;
                   color:#94a3b8;font-size:.66rem;text-transform:uppercase;
                   letter-spacing:.04em;font-weight:700;">
          <th style="padding:10px 12px;text-align:left;">Exercici</th>
          <th style="padding:10px 12px;text-align:left;">Escala de la base de l'estalvi</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table></div>
    <div style="font-size:.7rem;color:#94a3b8;margin-top:6px;">
      Les files destacades marquen els exercicis amb canvi normatiu; els
      anys intermedis hereten l'escala de l'últim canvi. El 2015 és un any
      de transició (s'apliquen els tipus consolidats oficials 20/22/24 %).
    </div>"""


# ─────────────────────────────────────────────────────────────
# RENDER: KPIs FISCALS
# ─────────────────────────────────────────────────────────────
def render_tax_kpis(
    capital_brut: float,
    capital_net: float,
    total_tax: float,
    total_disallowed: float,
    capital_inicial: float,
) -> str:
    """Genera l'HTML d'una fila de KPIs fiscals."""
    ret_brut = (capital_brut / capital_inicial - 1.0) * 100.0 if capital_inicial else 0.0
    ret_net = (capital_net / capital_inicial - 1.0) * 100.0 if capital_inicial else 0.0
    tax_drag = ret_brut - ret_net
    eff_rate = (total_tax / capital_brut * 100.0) if capital_brut > 0 else 0.0

    def _card(label, value, color, sub=""):
        sub_html = (
            f'<div style="font-size:.66rem;color:#94a3b8;margin-top:3px;">{sub}</div>'
            if sub else ""
        )
        return (
            f'<div style="flex:1;min-width:150px;background:#111111;'
            f'border:1px solid #2a2a2a;border-radius:12px;padding:13px 15px;">'
            f'<div style="font-size:.66rem;color:#94a3b8;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px;">{label}</div>'
            f'<div style="font-family:\'DM Mono\',monospace;font-size:1.02rem;'
            f'font-weight:700;color:{color};">{value}</div>{sub_html}</div>'
        )

    return (
        '<div style="display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 14px 0;">'
        + _card("Rendiment brut", f"{ret_brut:+.2f}%", "#16a34a" if ret_brut >= 0 else "#dc2626",
                "Abans d'impostos")
        + _card("Rendiment net", f"{ret_net:+.2f}%", "#16a34a" if ret_net >= 0 else "#dc2626",
                "Després d'IRPF")
        + _card("Impostos totals", f"{total_tax:,.2f}€", "#f59e0b",
                f"Tipus efectiu {eff_rate:.2f}%")
        + _card("Cost fiscal", f"−{tax_drag:.2f} pp", "#dc2626",
                "Rendiment perdut per IRPF")
        + _card("Pèrdues bloquejades", f"{total_disallowed:,.2f}€", "#a855f7",
                "Regla dels 2 mesos")
        + '</div>'
    )


# ─────────────────────────────────────────────────────────────
# RENDER: TAULA DE LIQUIDACIÓ ANUAL
# ─────────────────────────────────────────────────────────────
def render_yearly_tax_table(yearly: list[YearlyTaxResult]) -> str:
    """Genera l'HTML de la taula de liquidació exercici per exercici.

    Disseny en mode fosc per a consistència amb la resta del bot.
    """
    if not yearly:
        return (
            '<p style="color:#94a3b8;padding:14px;font-size:.85rem;">'
            'No hi ha exercicis amb operacions per liquidar.</p>'
        )

    rows = ""
    tot_gains = tot_loss_a = tot_loss_d = tot_tax = 0.0
    for i, y in enumerate(yearly):
        tot_gains += y.gains
        tot_loss_a += y.losses_allowed
        tot_loss_d += y.losses_disallowed
        tot_tax += y.tax
        # Files alternades en fosc (consistent amb la resta de taules
        # del bot, que ja funcionen bé sobre el tema fosc de Streamlit).
        bg = "#0f172a" if i % 2 == 0 else "#0a0a0a"
        tax_col = "#fbbf24" if y.tax > 0 else "#64748b"
        disallowed_cell = (
            f'<span style="color:#c4b5fd;">{y.losses_disallowed:,.2f}€</span>'
            if y.losses_disallowed > 0 else
            '<span style="color:#475569;">—</span>'
        )
        cf_cell = (
            f'<span style="color:#cbd5e1;">{y.carryforward_used:,.2f}€</span>'
            if y.carryforward_used > 0 else
            '<span style="color:#475569;">—</span>'
        )
        eff_txt = (
            f'<span style="color:#cbd5e1;">{y.effective_rate*100:.1f}%</span>'
            if y.net_base > 0 else
            '<span style="color:#475569;">—</span>'
        )
        rows += (
            f'<tr style="background:{bg};border-bottom:1px solid #1e293b;">'
            # Any: blanc, negreta, llegible
            f'<td style="padding:9px 12px;color:#f1f5f9;font-weight:700;">{y.year}</td>'
            # Escala aplicada: gris clar
            f'<td style="padding:9px 12px;font-size:.74rem;color:#94a3b8;">'
            f'{y.scale_label}</td>'
            # Guanys: verd
            f'<td style="padding:9px 12px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;color:#4ade80;">{y.gains:,.2f}€</td>'
            # Pèrdues computables: vermell
            f'<td style="padding:9px 12px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;color:#f87171;">{y.losses_allowed:,.2f}€</td>'
            # Pèrdues bloquejades: lila
            f'<td style="padding:9px 12px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;">{disallowed_cell}</td>'
            # Compensació d'anys anteriors
            f'<td style="padding:9px 12px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;">{cf_cell}</td>'
            # Base estalvi: blanc, negreta
            f'<td style="padding:9px 12px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;color:#f1f5f9;font-weight:600;">{y.net_base:,.2f}€</td>'
            # Quota IRPF: groc/taronja
            f'<td style="padding:9px 12px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;font-weight:700;color:{tax_col};">{y.tax:,.2f}€</td>'
            # Tipus efectiu
            f'<td style="padding:9px 12px;font-family:\'DM Mono\',monospace;'
            f'text-align:right;">{eff_txt}</td>'
            f'</tr>'
        )

    totals_row = (
        '<tr style="background:#1e293b;color:#f1f5f9;font-weight:700;'
        'border-top:2px solid #334155;">'
        '<td style="padding:11px 12px;color:#f1f5f9;" colspan="2">TOTAL</td>'
        f'<td style="padding:11px 12px;font-family:\'DM Mono\',monospace;'
        f'text-align:right;color:#4ade80;">{tot_gains:,.2f}€</td>'
        f'<td style="padding:11px 12px;font-family:\'DM Mono\',monospace;'
        f'text-align:right;color:#f87171;">{tot_loss_a:,.2f}€</td>'
        f'<td style="padding:11px 12px;font-family:\'DM Mono\',monospace;'
        f'text-align:right;color:#c4b5fd;">{tot_loss_d:,.2f}€</td>'
        '<td style="padding:11px 12px;"></td>'
        '<td style="padding:11px 12px;"></td>'
        f'<td style="padding:11px 12px;font-family:\'DM Mono\',monospace;'
        f'text-align:right;color:#fbbf24;">{tot_tax:,.2f}€</td>'
        '<td style="padding:11px 12px;"></td>'
        '</tr>'
    )

    return f"""
    <div style="overflow-x:auto;border:1px solid #2a2a2a;border-radius:12px;
                background:#0a0a0a;">
    <table style="width:100%;border-collapse:collapse;white-space:nowrap;
                  font-size:.83rem;color:#cbd5e1;">
      <thead>
        <tr style="background:#0a0a0a;border-bottom:1px solid #2a2a2a;
                   color:#94a3b8;font-size:.64rem;text-transform:uppercase;
                   letter-spacing:.05em;font-weight:700;">
          <th style="padding:11px 12px;text-align:left;">Exercici</th>
          <th style="padding:11px 12px;text-align:left;">Escala</th>
          <th style="padding:11px 12px;text-align:right;">Guanys</th>
          <th style="padding:11px 12px;text-align:right;">Pèrdues comput.</th>
          <th style="padding:11px 12px;text-align:right;">Pèrd. bloq. (2m)</th>
          <th style="padding:11px 12px;text-align:right;">Compens. ant.</th>
          <th style="padding:11px 12px;text-align:right;">Base estalvi</th>
          <th style="padding:11px 12px;text-align:right;">Quota IRPF</th>
          <th style="padding:11px 12px;text-align:right;">Efectiu</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
      <tfoot>{totals_row}</tfoot>
    </table></div>"""
