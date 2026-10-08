"""What is news, and what is it about, judged from the article's web address.

Almost every outlet puts the section in the URL (infobae.com/economia/...,
clarin.com/brandstudio/..., france24.com/es/deportes/...). That is a far more
reliable signal than guessing from words, and it exposes most ads and filler.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from .text import normalize

# URL section -> topic. Matched against every path segment (normalized, no accents).
SECTION_TOPICS: dict[str, str] = {}
for _topic, _sections in {
    "politics": "politica politics elecciones elections congreso gobierno",
    "economy": "economia economy finanzas mercados dinero ieco macro inflacion",
    "business": "negocios business empresas companies energia energy",
    "world": "mundo el-mundo internacional internacionales world europe europa middle-east medio-oriente "
             "africa asia asia-pacific asia-pacifico eeuu-y-canada americas oceania",
    "latam": "america america-latina latinoamerica latin-america",
    "security": "policiales seguridad crimen crime justicia",
    "sports": "deportes deporte sport sports futbol football soccer tenis tennis rugby basquet automovilismo ole",
    "technology": "tecnologia tecno technology tech malditos-nerds innovacion",
    "science": "ciencia science science-environment science_and_environment espacio space",
    "health": "salud health bienestar medicina",
    "environment": "medio-ambiente medioambiente environment climate cambio-climatico planeta",
    "education": "educacion education universidades",
    "culture": "cultura culture arts libros books musica music arte",
    "entertainment": "espectaculos teleshow entretenimiento entertainment famosos gente show farandula "
                     "cine series tv television que-puedo-ver celebrities",
    "lifestyle": "lifestyle buena-vida tendencias moda moda-y-belleza revista viajes turismo gastronomia "
                 "autos propiedades hogar mascotas living",
    "agro": "campo rural agro agricultura",
}.items():
    for _s in _sections.split():
        SECTION_TOPICS[_s] = _topic

# Sections that are never news: paid content, shopping, games, horoscopes, TV listings...
EXCLUDED_SECTIONS = set("""
brandstudio brand-studio inhouse contenido-patrocinado patrocinado sponsored sponsor publinota publirreportaje
especiales-comerciales especial-comercial comercial advertorial partner-content paid-post promociones promocion
ofertas shopping compras tienda descuentos cupones club-la-nacion clarin365 suscripciones newsletters
horoscopo horoscopos horoscope astrologia loterias loteria quiniela quinielas juegos games crucigramas wordle
servicios clima pronostico recetas recetas-faciles tv-shows programas podcasts fotogalerias feriados efemerides
""".split())

# Regional outlets also publish other countries' local news (infobae.com/mexico/...).
FOREIGN_EDITIONS = set("""
mexico colombia peru venezuela espana chile uruguay paraguay bolivia ecuador centroamerica estados-unidos usa
""".split())

# Paid content is usually labelled in the feed's categories...
AD_TAG_MARKERS = ["contenido patrocinado", "patrocinado", "sponsored", "publicidad", "advertorial",
                  "brand studio", "brandstudio", "nota comercial", "espacio de marca", "partner content"]
# ...and shopping pieces give themselves away in the headline. (Kept specific on purpose:
# "oferta de canje", "sorteo del Mundial" or "receta electronica" are real news.)
AD_TITLE_MARKERS = [
    "contenido patrocinado", "sponsored", "advertorial", "en alianza con", "hot sale", "black friday",
    "cyber monday", "cybermonday", "cyberweek", "codigo de descuento", "cupon de descuento", "cupones de descuento",
    "con descuento", "descuentos de hasta", "ofertas imperdibles", "las mejores ofertas", "mejores ofertas",
    "cuotas sin interes", "best deals", "deal of the day", "shop now", "comprar ahora",
]
FILLER_MARKERS = [
    "horoscopo", "horoscope", "tarot", "signos del zodiaco", "quiniela", "telekino", "brinco", "loto plus",
    "resultados de la loteria", "resultados del sorteo", "wordle", "crucigrama", "sudoku", "pronostico del tiempo",
    "pronostico del clima", "a cuanto cotiza", "dolar blue hoy", "dolar hoy", "dolar oficial hoy",
    "cotizacion del dolar", "como ver en vivo", "donde ver en vivo", "a que hora juega", "a que hora y donde",
    "que se celebra hoy", "efemerides", "santoral", "frase del dia", "trucos para", "tips para",
]

_DATE_OR_ID = re.compile(r"^(\d+|[a-z]?\d[\w-]*\d)$")


def url_sections(link: str) -> list[str]:
    """Path segments that look like sections (not dates, ids or the article slug)."""
    parts = [normalize(unquote(p)) for p in urlsplit(link).path.split("/") if p]
    if len(parts) > 1:
        parts = parts[:-1]  # the last segment is the article itself
    return [p for p in parts if not _DATE_OR_ID.match(p) and len(p) < 40 and p not in ("es", "en", "news", "noticias")]


def _has(text: str, phrases: list[str]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", text) for p in phrases)


def exclusion_reason(title: str, link: str, tags: list[str], region: str, country: str) -> str | None:
    sections = url_sections(link)
    if any(s in EXCLUDED_SECTIONS for s in sections):
        return "section"
    if _has(normalize(" ".join(tags)), AD_TAG_MARKERS) or _has(normalize(title), AD_TITLE_MARKERS):
        return "ad"
    if _has(normalize(title), FILLER_MARKERS):
        return "filler"
    if region != "global" and sections and sections[0] in FOREIGN_EDITIONS and sections[0] != _COUNTRY_SLUG.get(country):
        return "foreign-edition"
    return None


_COUNTRY_SLUG = {"MX": "mexico", "CO": "colombia", "PE": "peru", "ES": "espana", "CL": "chile", "UY": "uruguay",
                 "US": "estados-unidos"}


def section_topics(link: str) -> set[str]:
    return {SECTION_TOPICS[s] for s in url_sections(link) if s in SECTION_TOPICS}
