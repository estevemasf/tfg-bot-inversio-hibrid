"""
Helpers compartits: format CSV per descàrregues + càrrega de logos.
NO té dependències de Streamlit.
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import pandas as pd

from core.config import LOGOS_PATH


# ─────────────────────────────────────────────────────────────
# CSV BYTES (compatible Excel)
# ─────────────────────────────────────────────────────────────
def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    Format estàndard de CSV per a descàrregues (Excel-compatible):
    separador punt i coma, coma decimal, BOM UTF-8.
    """
    csv_str = df.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig")
    return csv_str.encode("utf-8-sig")


# ─────────────────────────────────────────────────────────────
# LOGOS — càrrega + cache + render HTML
# ─────────────────────────────────────────────────────────────
# Cache de logos a memòria (una sola crida de disc per empresa per sessió)
_LOGO_CACHE: dict = {}


def _load_logo_b64(ticker: str, company: str, logos_path: Path = LOGOS_PATH) -> str | None:
    """
    Carrega el logo d'una empresa des del disc i el retorna com a data-URI
    base64 (incrustable directament dins HTML).

    Convenció de fitxers: TICKER-Companyia.ext  (ex: AAPL-Apple.png)

    Matching tolerant:
      • Prova diverses extensions: .png, .jpg, .jpeg, .webp, .svg
      • Si no troba amb el nom exacte, prova normalitzant
      • Si tampoc, prova només amb el ticker (AAPL.png)
      • Si res, retorna None (les targetes es mostraran sense logo)

    Cacheat a memòria via `_LOGO_CACHE` per evitar relectures de disc.

    ROBUSTESA: si la ruta absoluta original no existeix (per exemple, si
    s'executa des d'un altre ordinador), prova fallbacks relatius:
      • ./logos/
      • ../logos/
    """
    cache_key = f"{ticker}|{company}"
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key]

    logos_path = Path(logos_path)
    candidate_paths = [logos_path]

    # Fallbacks per si la ruta absoluta no existeix (executar en altre màquina)
    if not logos_path.exists():
        candidate_paths.extend([
            Path.cwd() / "logos",
            Path.cwd().parent / "logos",
            Path(__file__).resolve().parent.parent / "logos",
        ])

    # Trobem el primer path que existeix
    active_path = None
    for p in candidate_paths:
        if p.exists():
            active_path = p
            break

    if active_path is None:
        _LOGO_CACHE[cache_key] = None
        return None

    def _norm(s: str) -> str:
        return str(s).strip().replace("  ", " ")

    tk = _norm(ticker)
    cn = _norm(company)

    stem_candidates = [
        f"{tk}-{cn}",
        f"{tk} - {cn}",
        f"{tk}_{cn}",
        tk,
        cn,
    ]
    seen = set()
    stem_candidates = [s for s in stem_candidates if not (s in seen or seen.add(s))]

    extensions = [".png", ".jpg", ".jpeg", ".webp", ".svg"]

    found = None
    for stem in stem_candidates:
        for ext in extensions:
            p = active_path / f"{stem}{ext}"
            if p.exists():
                found = p
                break
        if found:
            break

    # Fallback: escaneig fuzzy
    if found is None:
        tk_upper = tk.upper()
        for p in active_path.iterdir():
            if p.is_file() and p.suffix.lower() in extensions:
                stem_upper = p.stem.upper()
                if (stem_upper.startswith(tk_upper + "-")
                    or stem_upper.startswith(tk_upper + " ")
                    or stem_upper == tk_upper):
                    found = p
                    break

    if found is None:
        _LOGO_CACHE[cache_key] = None
        return None

    try:
        mime, _ = mimetypes.guess_type(str(found))
        if mime is None:
            mime = "image/png"
        with open(found, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        uri = f"data:{mime};base64,{data}"
        _LOGO_CACHE[cache_key] = uri
        return uri
    except Exception:
        _LOGO_CACHE[cache_key] = None
        return None


def _logo_html(ticker: str, company: str, size: int = 36,
               logos_path: Path = LOGOS_PATH,
               style_extra: str = "") -> str:
    """
    Retorna un snippet HTML d'un logo d'empresa com a cercle
    amb fons negre i anell subtil (estil app/stock).

    Si el logo no existeix, mostra un cercle amb les inicials del ticker.
    """
    uri = _load_logo_b64(ticker, company, logos_path)
    common = (
        f"width:{size}px;height:{size}px;"
        f"border-radius:50%;flex-shrink:0;"
        f"background:#000;"
        f"border:1.5px solid rgba(148,163,184,0.35);"
        f"box-shadow:0 1px 4px rgba(0,0,0,.35),"
        f"inset 0 0 0 1px rgba(255,255,255,.04);"
        f"{style_extra}"
    )
    if uri:
        return (
            f'<div style="{common}display:flex;align-items:center;justify-content:center;'
            f'overflow:hidden;padding:4px;">'
            f'<img src="{uri}" alt="{ticker}" '
            f'style="max-width:100%;max-height:100%;object-fit:contain;display:block;" />'
            f'</div>'
        )
    initials = (ticker or "?")[:3].upper()
    return (
        f'<div style="{common}display:flex;align-items:center;justify-content:center;'
        f'color:#94a3b8;font-family:\'DM Mono\',monospace;font-weight:700;'
        f'font-size:{max(9, size // 3)}px;letter-spacing:.02em;">'
        f'{initials}</div>'
    )
