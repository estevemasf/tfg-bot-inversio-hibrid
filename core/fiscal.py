"""
core/fiscal.py — Mòdul de fiscalitat de l'estalvi (IRPF espanyol).

Aquest mòdul NO té cap dependència de Streamlit. Modela la tributació
dels guanys i pèrdues patrimonials derivats de la compravenda de valors,
seguint el règim de la BASE IMPOSABLE DE L'ESTALVI de l'IRPF espanyol.

═══════════════════════════════════════════════════════════════════════
QUÈ MODELA (i amb quin nivell de fidelitat)
═══════════════════════════════════════════════════════════════════════

1. ESCALA PROGRESSIVA DE L'ESTALVI — VIGENT PER EXERCICI
   La base de l'estalvi NO tributa a un tipus pla, sinó per trams. A més,
   el model NO aplica una escala única a tot el període: cada exercici
   tributa amb l'escala REALMENT VIGENT aquell any. Evolució 2014–2025:
       • 2014:      21 / 25 / 27 % (límits 6.000 i 24.000 €)
       • 2015:      20 / 22 / 24 % (any de transició de la reforma)
       • 2016–2020: 19 / 21 / 23 %
       • 2021–2022: 19 / 21 / 23 / 26 % (nou tram >200.000 €)
       • 2023–2024: 19 / 21 / 23 / 27 / 28 %
       • 2025:      19 / 21 / 23 / 27 / 30 % (Ley 7/2024)
   Així, una plusvàlua de 2016 tributa amb la normativa de 2016, no amb
   la de 2025. Tots els trams són configurables (TaxConfig) i es pot
   forçar una escala fixa per a anàlisi de sensibilitat (per_year_scale).

2. LIQUIDACIÓ ANUAL
   Cada any natural és un fet imposable independent. Es calcula la base
   de l'estalvi de l'any = (guanys realitzats − pèrdues compensables),
   s'hi aplica l'escala, i l'impost resultant es considera pagat (el
   backtest el resta del capital). Aquesta és la diferència CLAU entre
   una estratègia activa i un Buy & Hold:
       • L'estratègia realitza guanys cada any → tributa cada any.
       • El B&H difereix tota la tributació al tancament final → gaudeix
         de l'anomenat "diferiment fiscal" (l'impost no pagat continua
         capitalitzant-se).

3. REGLA DELS DOS MESOS (regla anti-aplicació, art. 33.5.f LIRPF)
   Si es ven un valor amb PÈRDUA i es recompra el MATEIX valor dins dels
   2 mesos anteriors o posteriors, la pèrdua NO es pot computar fiscalment
   en aquell exercici: queda "aparcada" i s'allibera quan es transmet la
   posició recomprada (sempre que no hi torni a haver recompra). Una
   estratègia de reversal que entra i surt sovint del mateix actiu hi
   topa contínuament; modelar-ho fa el resultat fiscal molt més realista.

4. COMPENSACIÓ I ARROSSEGAMENT DE PÈRDUES
   Dins d'un mateix exercici, les pèrdues compensen guanys sense límit.
   Si després de compensar queda un saldo negatiu, s'arrossega i pot
   compensar guanys dels 4 exercicis següents. (Es modela el cas de
   valors; s'omet la compensació creuada amb rendiments del capital
   mobiliari i el seu límit del 25 %, ja que el backtest no genera
   dividends ni interessos.)

═══════════════════════════════════════════════════════════════════════
SIMPLIFICACIONS ASSUMIDES (declarar-les al treball)
═══════════════════════════════════════════════════════════════════════
• No es modelen dividends ni les seves retencions.
• No es modela la compensació creuada estalvi ↔ rendiments del capital
  mobiliari (límit del 25 %).
• El llindar exempt (`exempt_threshold`) és un artefacte de modelització
  per fer anàlisi de sensibilitat: la normativa NO preveu cap mínim
  exempt per a guanys patrimonials de valors. Per defecte és 0 €.
• L'impost de l'any N es considera "pagat" a efectes de capital el
  mateix tancament del 31/12/N (simplificació de caixa). A la realitat
  es pagaria amb la declaració de l'any següent (juny de N+1); modelar
  aquest desfàs de caixa exacte complicaria la corba d'equity sense
  canviar les conclusions, així que s'aplica al tancament de l'exercici.
• FIFO: la cartera inverteix el 100 % i tanca posicions senceres, de
  manera que no hi ha lots parcials i el FIFO és trivialment respectat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd


# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓ FISCAL
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TaxBracket:
    """Un tram de l'escala de l'estalvi.

    `up_to` és el límit superior de la base acumulada (en €) al qual
    s'aplica `rate`. L'últim tram té `up_to = None` (sense límit).
    """
    up_to: float | None
    rate: float  # p.ex. 0.19 = 19 %


# Escala de l'estalvi vigent per a l'exercici 2025 (declaració 2026).
#
# IMPORTANT — actualització normativa: la Ley 7/2024, de 20 de desembre
# (BOE 21/12/2024), disposició final 7a, va modificar l'escala de la base
# liquidable de l'estalvi de l'IRPF amb efectes des de l'1/01/2025. L'antic
# darrer tram (>200.000 € al 28 %) es desdobla en dos:
#       • 200.000 – 300.000 € → 27 % (sense canvi)
#       • > 300.000 €         → 30 % (abans 28 %; pujada de 2 punts)
# Els quatre primers trams (19/21/23/27 %) no canvien. Per a un inversor
# particular amb una cartera petita, a la pràctica només són rellevants
# els trams del 19 % i el 21 %.
SPAIN_SAVINGS_BRACKETS_2025: tuple[TaxBracket, ...] = (
    TaxBracket(up_to=6_000.0,   rate=0.19),
    TaxBracket(up_to=50_000.0,  rate=0.21),
    TaxBracket(up_to=200_000.0, rate=0.23),
    TaxBracket(up_to=300_000.0, rate=0.27),
    TaxBracket(up_to=None,      rate=0.30),
)


# ─────────────────────────────────────────────────────────────
# ESCALA DE L'ESTALVI PER EXERCICI FISCAL (2014–2025)
# ─────────────────────────────────────────────────────────────
# Millora metodològica: en comptes d'aplicar l'escala de 2025 de forma
# retroactiva a tot el període, el model aplica l'escala REALMENT VIGENT
# en cada exercici. Una plusvàlua realitzada el 2016 tributa amb la
# normativa de 2016, no amb la de 2025. Això evita la crítica d'aplicar
# tipus actuals a resultats antics i fa el backtest fidel a l'evolució
# normativa de l'IRPF durant el període 2014–2025.
#
# FONTS I NOTES PER EXERCICI:
#   • 2014: escala anterior a la reforma (Ley 26/2014). Tres trams:
#           21 % fins a 6.000 €, 25 % fins a 24.000 €, 27 % la resta.
#   • 2015: ANY DE TRANSICIÓ. La reforma de 2015 es va aplicar en dos
#           trams temporals; l'AEAT en va publicar el tipus mitjà anual
#           consolidat. La taula oficial de l'exercici 2015 recull
#           20 % / 22 % / 24 % (límits 6.000 i 50.000 €). Alguns
#           manuals citen els tipus mitjos 19,5 / 21,5 / 23,5 %. Aquí
#           s'usen els CONSOLIDATS oficials (20/22/24); si el tutor
#           prefereix els mitjos, només cal editar aquesta entrada o
#           els controls de la pestanya Fiscalitat.
#   • 2016–2020: escala estable de tres trams 19 / 21 / 23 %.
#   • 2021–2022: s'afegeix un quart tram del 26 % per sobre de
#           200.000 € (Ley 11/2020 de pressupostos per al 2021).
#   • 2023–2024: cinc trams; el tram alt es desdobla en 27 % (fins a
#           300.000 €) i 28 % (la resta) (Ley 31/2022).
#   • 2025: el darrer tram puja del 28 % al 30 % (Ley 7/2024).
#
# Estructura: {any: ((límit|None, tipus), ...)}. L'últim tram de cada
# any té límit None (sense sostre).
SPAIN_SAVINGS_BRACKETS_BY_YEAR: dict[int, tuple[TaxBracket, ...]] = {
    2014: (
        TaxBracket(24_000.0, 0.25),
        TaxBracket(6_000.0,  0.21),  # ordre lògic es normalitza a sota
        TaxBracket(None,     0.27),
    ),
    2015: (
        TaxBracket(6_000.0,  0.20),
        TaxBracket(50_000.0, 0.22),
        TaxBracket(None,     0.24),
    ),
    2016: (
        TaxBracket(6_000.0,  0.19),
        TaxBracket(50_000.0, 0.21),
        TaxBracket(None,     0.23),
    ),
    2021: (
        TaxBracket(6_000.0,   0.19),
        TaxBracket(50_000.0,  0.21),
        TaxBracket(200_000.0, 0.23),
        TaxBracket(None,      0.26),
    ),
    2023: (
        TaxBracket(6_000.0,   0.19),
        TaxBracket(50_000.0,  0.21),
        TaxBracket(200_000.0, 0.23),
        TaxBracket(300_000.0, 0.27),
        TaxBracket(None,      0.28),
    ),
    2025: SPAIN_SAVINGS_BRACKETS_2025,
}


def _normalize_brackets(brackets: tuple[TaxBracket, ...]) -> tuple[TaxBracket, ...]:
    """Ordena els trams per límit creixent (l'últim, None, al final).

    Els trams del diccionari es poden haver escrit en qualsevol ordre;
    el càlcul progressiu de `tax_on_base` necessita que estiguin ordenats
    de límit més baix a més alt.
    """
    finite = sorted(
        (b for b in brackets if b.up_to is not None),
        key=lambda b: b.up_to,
    )
    infinite = [b for b in brackets if b.up_to is None]
    return tuple(finite) + tuple(infinite)


def brackets_for_year(year: int) -> tuple[TaxBracket, ...]:
    """Retorna l'escala de l'estalvi vigent per a un exercici fiscal.

    Com que algunes escales es mantenen estables diversos anys, el
    diccionari només té entrades als anys de CANVI. Per a un any sense
    entrada pròpia, s'agafa l'escala de l'any de canvi immediatament
    anterior (p.ex. 2018 → usa l'entrada de 2016; 2022 → la de 2021).

    Per a anys posteriors a l'última escala coneguda (>2025), s'aplica
    provisionalment l'última escala disponible, amb el benentès que
    caldria actualitzar el diccionari quan es conegui la nova normativa.

    Args:
        year: exercici fiscal (any natural de la data de venda).

    Returns:
        Tupla de TaxBracket ja ordenada per a aquell exercici.
    """
    known = sorted(SPAIN_SAVINGS_BRACKETS_BY_YEAR.keys())
    if year < known[0]:
        chosen = known[0]
    elif year > known[-1]:
        chosen = known[-1]
    else:
        # L'any de canvi més recent que sigui <= year
        chosen = max(y for y in known if y <= year)
    return _normalize_brackets(SPAIN_SAVINGS_BRACKETS_BY_YEAR[chosen])


@dataclass
class TaxConfig:
    """Paràmetres fiscals configurables des de la UI.

    Attributes:
        enabled: si False, tot el mòdul és transparent (impost = 0).
        brackets: trams de l'escala progressiva. NOMÉS s'usa si
            `per_year_scale` és False (mode escala fixa).
        apply_two_month_rule: activa la regla anti-aplicació dels 2 mesos.
        loss_carryforward_years: anys que una pèrdua es pot arrossegar
            (normativa: 4).
        exempt_threshold: mínim exempt anual de la base (€). Per defecte
            0 (la normativa no en preveu cap per a valors); útil només
            per a anàlisi de sensibilitat.
        per_year_scale: si True (DEFECTE), cada exercici tributa amb
            l'escala REALMENT VIGENT aquell any (via brackets_for_year).
            Si False, s'aplica `brackets` —una escala fixa— a tots els
            exercicis (útil per a anàlisi de sensibilitat o per veure
            l'efecte d'aplicar retroactivament una escala única).
        brackets_by_year: permet sobreescriure les escales per exercici
            (p.ex. des de la UI). Si és None, s'usa el diccionari oficial
            SPAIN_SAVINGS_BRACKETS_BY_YEAR.
    """
    enabled: bool = True
    brackets: tuple[TaxBracket, ...] = SPAIN_SAVINGS_BRACKETS_2025
    apply_two_month_rule: bool = True
    loss_carryforward_years: int = 4
    exempt_threshold: float = 0.0
    per_year_scale: bool = True
    brackets_by_year: dict[int, tuple[TaxBracket, ...]] | None = None

    def brackets_for(self, year: int) -> tuple[TaxBracket, ...]:
        """Retorna l'escala a aplicar per a un exercici fiscal concret.

        Si `per_year_scale` és True, tria l'escala vigent d'aquell any
        (del diccionari propi `brackets_by_year` si n'hi ha, o de
        l'oficial). Si és False, retorna sempre `self.brackets`.
        """
        if not self.per_year_scale:
            return _normalize_brackets(self.brackets)
        if self.brackets_by_year is not None:
            known = sorted(self.brackets_by_year.keys())
            if known:
                if year < known[0]:
                    chosen = known[0]
                elif year > known[-1]:
                    chosen = known[-1]
                else:
                    chosen = max(y for y in known if y <= year)
                return _normalize_brackets(self.brackets_by_year[chosen])
        return brackets_for_year(year)

    @staticmethod
    def flat(rate: float, enabled: bool = True) -> "TaxConfig":
        """Crea una configuració de tipus PLA (un sol tram, escala fixa).

        Útil per comparar l'escala progressiva amb un tipus efectiu únic.
        """
        return TaxConfig(
            enabled=enabled,
            brackets=(TaxBracket(up_to=None, rate=rate),),
            apply_two_month_rule=True,
            per_year_scale=False,
        )


# ─────────────────────────────────────────────────────────────
# CÀLCUL DE LA QUOTA PER ESCALA PROGRESSIVA
# ─────────────────────────────────────────────────────────────
def tax_on_base(base: float, cfg: TaxConfig, year: int | None = None) -> float:
    """Aplica l'escala progressiva a una base de l'estalvi positiva.

    La progressivitat és per trams (com l'IRPF): cada porció de la base
    tributa al tipus del seu tram, no tota la base al tipus marginal.

    Exemple amb l'escala 2025 i una base de 60.000 €:
        6.000 × 19 %           = 1.140 €
        (50.000−6.000) × 21 %  = 9.240 €
        (60.000−50.000) × 23 % = 2.300 €
        ───────────────────────────────
        quota total            = 12.680 €

    Args:
        base: base de l'estalvi de l'any (€). Si és ≤ 0 la quota és 0.
        cfg: configuració fiscal.
        year: exercici fiscal. Si cfg.per_year_scale és True, determina
            quina escala s'aplica (la vigent aquell any). Si és None,
            s'usa l'escala fixa cfg.brackets (compatibilitat enrere).

    Returns:
        Quota íntegra de l'estalvi (€), arrodonida a 2 decimals.
    """
    if not cfg.enabled or base <= 0:
        return 0.0

    # Escala aplicable: depèn de l'exercici si està activat el mode
    # per-any; si no, l'escala fixa de cfg.brackets.
    if year is not None:
        brackets = cfg.brackets_for(year)
    else:
        brackets = _normalize_brackets(cfg.brackets)

    # El llindar exempt es resta abans d'aplicar l'escala.
    taxable = max(0.0, base - max(0.0, cfg.exempt_threshold))
    if taxable <= 0:
        return 0.0

    quota = 0.0
    lower = 0.0
    for br in brackets:
        upper = br.up_to if br.up_to is not None else float("inf")
        if taxable <= lower:
            break
        # Porció de la base que cau dins d'aquest tram
        portion = min(taxable, upper) - lower
        if portion > 0:
            quota += portion * br.rate
        lower = upper

    return round(quota, 2)


def effective_rate(base: float, cfg: TaxConfig) -> float:
    """Tipus EFECTIU (quota / base) per a una base donada, en tant per u.

    És sempre ≤ al tipus marginal. Útil per a la pestanya informativa.
    """
    if base <= 0:
        return 0.0
    return round(tax_on_base(base, cfg) / base, 4)


# ─────────────────────────────────────────────────────────────
# ESDEVENIMENT FISCAL: una venda realitzada
# ─────────────────────────────────────────────────────────────
@dataclass
class TaxableSale:
    """Una transmissió de valors amb el seu resultat (guany o pèrdua).

    Es construeix a partir d'una operació tancada del backtest.

    Attributes:
        ticker: valor transmès (clau per a la regla dels 2 mesos).
        sell_date: data de la venda.
        buy_date: data de la compra corresponent.
        pnl: resultat net de l'operació en € (positiu = guany).
        disallowed: True si la pèrdua queda bloquejada per la regla dels
            2 mesos (només té sentit si pnl < 0).
    """
    ticker: str
    sell_date: date
    buy_date: date
    pnl: float
    disallowed: bool = False


def _to_date(value) -> date:
    """Converteix string / Timestamp / datetime a datetime.date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    # string tipus 'YYYY-MM-DD' (pot dur sufix ' *' del forced_close)
    s = str(value).replace("*", "").strip()[:10]
    return datetime.strptime(s, "%Y-%m-%d").date()


# ─────────────────────────────────────────────────────────────
# REGLA DELS DOS MESOS
# ─────────────────────────────────────────────────────────────
def flag_two_month_rule(sales: list[TaxableSale]) -> list[TaxableSale]:
    """Marca quines vendes amb pèrdua queden bloquejades per la regla
    anti-aplicació dels 2 mesos.

    Criteri (art. 33.5.f LIRPF): una pèrdua per la transmissió d'un
    valor NO es computa si s'ha adquirit el MATEIX valor homogeni dins
    dels 2 mesos anteriors o posteriors a aquella transmissió.

    Implementació: per cada venda amb pèrdua, es busca si existeix
    QUALSEVOL compra del mateix ticker amb data dins de
    [sell_date − 2 mesos, sell_date + 2 mesos]. La pròpia compra que
    va originar la posició venuda no compta (és anterior i ja "consumida");
    el que es busca és una RECOMPRA distinta dins de la finestra.

    Modifica i retorna la mateixa llista (amb el camp `disallowed`).

    Nota de modelització: s'aproxima "2 mesos" com 60 dies naturals per
    simetria i simplicitat. La normativa parla de mesos de calendari;
    la diferència és menor i es declara com a simplificació.
    """
    window = timedelta(days=60)

    # Totes les dates de COMPRA per ticker (incloent la d'obertura de
    # cada posició: una recompra és, al cap i a la fi, una nova compra).
    buys_by_ticker: dict[str, list[date]] = {}
    for s in sales:
        buys_by_ticker.setdefault(s.ticker, []).append(s.buy_date)

    for s in sales:
        s.disallowed = False
        if s.pnl >= 0:
            continue  # la regla només afecta PÈRDUES
        # Busquem una compra del mateix ticker dins la finestra de ±2 mesos
        # que NO sigui la compra que va originar aquesta mateixa venda.
        for buy_d in buys_by_ticker.get(s.ticker, []):
            if buy_d == s.buy_date:
                continue  # és la compra pròpia de la posició venuda
            if abs((buy_d - s.sell_date).days) <= window.days:
                s.disallowed = True
                break

    return sales


# ─────────────────────────────────────────────────────────────
# LIQUIDACIÓ ANUAL AMB COMPENSACIÓ I ARROSSEGAMENT
# ─────────────────────────────────────────────────────────────
@dataclass
class YearlyTaxResult:
    """Resultat de la liquidació d'un exercici fiscal."""
    year: int
    gains: float                 # suma de guanys realitzats l'any
    losses_allowed: float        # pèrdues computables l'any (valor positiu)
    losses_disallowed: float     # pèrdues bloquejades per la regla 2 mesos
    carryforward_used: float     # pèrdues d'anys anteriors aplicades
    net_base: float              # base de l'estalvi després de compensar
    tax: float                   # quota a pagar
    carryforward_remaining: float  # pèrdues que queden per arrossegar
    scale_label: str = ""        # escala aplicada, p.ex. "19/21/23 %"
    effective_rate: float = 0.0  # tipus efectiu de l'any (quota/base)


def _scale_label(brackets: tuple[TaxBracket, ...]) -> str:
    """Genera una etiqueta curta dels tipus d'una escala, p.ex. '19/21/23 %'."""
    rates = [f"{b.rate * 100:g}" for b in brackets]
    return "/".join(rates) + " %"


def compute_yearly_taxes(
    sales: list[TaxableSale],
    cfg: TaxConfig,
) -> list[YearlyTaxResult]:
    """Liquida l'impost any per any aplicant compensació i arrossegament.

    Procediment per a cada exercici (en ordre cronològic):
        1. Es sumen els guanys de l'any i les pèrdues COMPUTABLES
           (les bloquejades per la regla dels 2 mesos s'exclouen).
        2. Les pèrdues de l'any compensen els guanys de l'any.
        3. Si encara queden guanys, s'hi apliquen les pèrdues
           arrossegades d'exercicis anteriors (FIFO entre anys, fins al
           límit de `loss_carryforward_years`).
        4. La base resultant (si és positiva) tributa per l'escala.
        5. Si el saldo de l'any és negatiu, s'afegeix a la bossa de
           pèrdues per arrossegar.

    Args:
        sales: totes les vendes del backtest (ja marcades amb la regla
            dels 2 mesos via `flag_two_month_rule`, si escau).
        cfg: configuració fiscal.

    Returns:
        Llista de YearlyTaxResult, un per exercici amb activitat,
        ordenada cronològicament.
    """
    if not cfg.enabled or not sales:
        return []

    # Agrupem per any
    by_year: dict[int, list[TaxableSale]] = {}
    for s in sales:
        by_year.setdefault(s.sell_date.year, []).append(s)

    # Bossa de pèrdues pendents d'arrossegar: {any_origen: import_positiu}
    pending_losses: dict[int, float] = {}
    results: list[YearlyTaxResult] = []

    for year in sorted(by_year.keys()):
        year_sales = by_year[year]

        gains = sum(s.pnl for s in year_sales if s.pnl > 0)

        losses_allowed = sum(
            -s.pnl for s in year_sales
            if s.pnl < 0 and not s.disallowed
        )
        losses_disallowed = sum(
            -s.pnl for s in year_sales
            if s.pnl < 0 and s.disallowed
        )

        # 1) Pèrdues de l'any compensen guanys de l'any
        net = gains - losses_allowed

        carryforward_used = 0.0
        if net > 0 and pending_losses:
            # 2) Apliquem pèrdues arrossegades (les més antigues primer),
            #    descartant les que ja han caducat (> loss_carryforward_years).
            for origin_year in sorted(pending_losses.keys()):
                if net <= 0:
                    break
                age = year - origin_year
                if age > cfg.loss_carryforward_years:
                    # Caducada: s'elimina sense efecte
                    pending_losses[origin_year] = 0.0
                    continue
                avail = pending_losses[origin_year]
                use = min(avail, net)
                net -= use
                carryforward_used += use
                pending_losses[origin_year] = avail - use

        # 3) Neteja de bosses esgotades o caducades
        pending_losses = {
            y: v for y, v in pending_losses.items()
            if v > 0.005 and (year - y) <= cfg.loss_carryforward_years
        }

        # 4) Si el saldo de l'any (després de compensar amb l'any) és
        #    negatiu, aquest excés va a la bossa d'arrossegament.
        if gains - losses_allowed < 0:
            pending_losses[year] = pending_losses.get(year, 0.0) + (
                losses_allowed - gains
            )

        net_base = max(0.0, net)
        # L'impost s'aplica amb l'escala VIGENT de l'exercici `year`.
        # Aquest és el canvi clau: el saldo de cada any tributa amb la
        # normativa d'aquell any, no amb una escala única retroactiva.
        tax = tax_on_base(net_base, cfg, year=year)

        carryforward_remaining = round(sum(pending_losses.values()), 2)

        # Etiqueta de l'escala aplicada aquest exercici i tipus efectiu,
        # per mostrar a la taula de liquidació de la pestanya Fiscalitat.
        year_brackets = cfg.brackets_for(year)
        scale_lbl = _scale_label(year_brackets)
        eff_rate = round(tax / net_base, 4) if net_base > 0 else 0.0

        results.append(YearlyTaxResult(
            year=year,
            gains=round(gains, 2),
            losses_allowed=round(losses_allowed, 2),
            losses_disallowed=round(losses_disallowed, 2),
            carryforward_used=round(carryforward_used, 2),
            net_base=round(net_base, 2),
            tax=round(tax, 2),
            carryforward_remaining=carryforward_remaining,
            scale_label=scale_lbl,
            effective_rate=eff_rate,
        ))

    return results


# ─────────────────────────────────────────────────────────────
# CONSTRUCCIÓ D'ESDEVENIMENTS FISCALS DES DE LES OPERACIONS
# ─────────────────────────────────────────────────────────────
def sales_from_trades(
    trades: list[dict],
    ticker: str,
) -> list[TaxableSale]:
    """Converteix les operacions d'un backtest (un actiu) en TaxableSale.

    Cada operació tancada (`trades` de run_strategy_backtest) és una
    transmissió. El resultat fiscal és el camp 'Guany/Perdua', que ja
    inclou comissions i slippage (resultat NET de l'operació).

    Args:
        trades: llista d'operacions de result["trades"].
        ticker: identificador del valor (per a la regla dels 2 mesos).

    Returns:
        Llista de TaxableSale, una per operació.
    """
    sales: list[TaxableSale] = []
    for t in trades:
        try:
            buy_d = _to_date(t["Entrada"])
            sell_d = _to_date(t["Sortida"])
        except (KeyError, ValueError):
            continue
        pnl = float(t.get("Guany/Perdua", 0.0))
        sales.append(TaxableSale(
            ticker=ticker,
            sell_date=sell_d,
            buy_date=buy_d,
            pnl=pnl,
        ))
    return sales


# ─────────────────────────────────────────────────────────────
# API D'ALT NIVELL: liquidació completa d'un conjunt d'operacions
# ─────────────────────────────────────────────────────────────
@dataclass
class TaxSummary:
    """Resultat fiscal complet d'una estratègia (un actiu o una cartera).

    Attributes:
        yearly: liquidació exercici per exercici.
        total_tax: suma de totes les quotes pagades (€).
        total_gains: guanys bruts realitzats acumulats (€).
        total_losses_allowed: pèrdues computables acumulades (€).
        total_losses_disallowed: pèrdues bloquejades per la regla dels
            2 mesos, acumulades (€).
        sales: les vendes individuals (amb el flag `disallowed`).
    """
    yearly: list[YearlyTaxResult] = field(default_factory=list)
    total_tax: float = 0.0
    total_gains: float = 0.0
    total_losses_allowed: float = 0.0
    total_losses_disallowed: float = 0.0
    sales: list[TaxableSale] = field(default_factory=list)


def compute_tax_summary(
    sales: list[TaxableSale],
    cfg: TaxConfig,
) -> TaxSummary:
    """Pipeline complet: regla dels 2 mesos + liquidació anual + agregats.

    És el punt d'entrada principal del mòdul. Donat un conjunt de vendes
    (d'un sol actiu o de tota la cartera) i una configuració fiscal,
    retorna el TaxSummary amb tot el detall.

    Args:
        sales: vendes a liquidar (de sales_from_trades, possiblement
            concatenades de diversos actius per a una cartera).
        cfg: configuració fiscal.

    Returns:
        TaxSummary complet. Si cfg.enabled és False, retorna un resum
        buit amb total_tax = 0.
    """
    if not cfg.enabled or not sales:
        return TaxSummary(sales=sales or [])

    # 1) Marquem les pèrdues bloquejades per la regla dels 2 mesos
    if cfg.apply_two_month_rule:
        sales = flag_two_month_rule(list(sales))
    else:
        for s in sales:
            s.disallowed = False

    # 2) Liquidació any per any
    yearly = compute_yearly_taxes(sales, cfg)

    # 3) Agregats
    total_tax = round(sum(y.tax for y in yearly), 2)
    total_gains = round(sum(s.pnl for s in sales if s.pnl > 0), 2)
    total_losses_allowed = round(
        sum(-s.pnl for s in sales if s.pnl < 0 and not s.disallowed), 2
    )
    total_losses_disallowed = round(
        sum(-s.pnl for s in sales if s.pnl < 0 and s.disallowed), 2
    )

    return TaxSummary(
        yearly=yearly,
        total_tax=total_tax,
        total_gains=total_gains,
        total_losses_allowed=total_losses_allowed,
        total_losses_disallowed=total_losses_disallowed,
        sales=sales,
    )


# ─────────────────────────────────────────────────────────────
# APLICACIÓ DE L'IMPOST A UNA CORBA D'EQUITY
# ─────────────────────────────────────────────────────────────
def apply_tax_to_equity(
    equity_points: list[dict],
    yearly: list[YearlyTaxResult],
) -> list[dict]:
    """Genera una corba d'equity NETA D'IMPOSTOS a partir d'una corba
    bruta i de la liquidació anual.

    L'impost de l'exercici N es resta de la corba a partir del darrer
    punt de l'any N (tancament del 31/12). Com que els impostos són
    acumulatius, cada punt es redueix per la suma de tots els impostos
    d'exercicis ja tancats en aquella data.

    Visualment, la corba neta d'impostos cau en "graons" cada final
    d'any en què s'ha tributat.

    Args:
        equity_points: corba bruta [{'time': 'YYYY-MM-DD', 'value': €}].
        yearly: liquidació anual de compute_yearly_taxes.

    Returns:
        Nova llista de punts amb el valor net d'impostos. No modifica
        l'original.
    """
    if not equity_points:
        return []
    if not yearly:
        return [dict(p) for p in equity_points]

    # Impost acumulat aplicable a partir de cada any
    tax_by_year = {y.year: y.tax for y in yearly}

    out: list[dict] = []
    for p in equity_points:
        p_date = _to_date(p["time"])
        # Suma dels impostos de tots els exercicis JA tancats en aquesta data.
        # Un exercici N es considera tancat (i el seu impost ja descomptat)
        # a partir del 31/12/N inclòs.
        cumulative_tax = sum(
            tax for yr, tax in tax_by_year.items()
            if p_date >= date(yr, 12, 31)
        )
        out.append({
            "time": p["time"],
            "value": round(float(p["value"]) - cumulative_tax, 4),
        })
    return out
