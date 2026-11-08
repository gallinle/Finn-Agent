"""Antwort-Mail deterministisch per Jinja2 rendern."""

from __future__ import annotations

from datetime import date

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from finn.calc.covenants import VertragsErgebnis
from finn.report import format as fmt

_env = Environment(
    loader=PackageLoader("finn.report", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals["fmt"] = fmt


def render(
    ergebnisse: list[VertragsErgebnis],
    zusammenfassung: str,
    stichtag: date,
    plan_datei: str,
    nicht_gefunden: set[tuple[int, str]] | None = None,
    hinweise: list[str] | None = None,
) -> tuple[str, str]:
    """Liefert (html, text). nicht_gefunden: (seite, zitat) nicht verifizierter Zitate."""
    ctx = dict(
        ergebnisse=ergebnisse,
        zusammenfassung=zusammenfassung,
        stichtag=stichtag,
        plan_datei=plan_datei,
        ungeprueft=nicht_gefunden is None,
        nicht_gefunden=nicht_gefunden or set(),
        hinweise=hinweise or [],
    )
    html = _env.get_template("antwort.html.j2").render(**ctx)
    text = _env.get_template("antwort.txt.j2").render(**ctx)
    return html, text


def render_fehler(grund: str, details: str | None = None) -> tuple[str, str]:
    ctx = dict(grund=grund, details=details)
    return (
        _env.get_template("fehler.html.j2").render(**ctx),
        _env.get_template("fehler.txt.j2").render(**ctx),
    )
