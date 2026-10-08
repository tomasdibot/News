"""Small, dependency-free text helpers for English and Spanish."""

from __future__ import annotations

import html
import re
import unicodedata

STOPWORDS = set("""
a about after against all also an and any are as at be been before being but by can could did do does
during for from had has have he her his how i if in into is it its just more most new no not now of on
one or other our out over said says she so some than that the their them then there these they this
those through to two under up us was we were what when where which while who why will with would year
years you your amid back first last week day days time make made get gets told according report reports
al algo ante antes como con contra cual cuando de del desde donde dos durante e el ella ellas ellos en
entre era es esa ese eso esta estas este esto estos fue fueron ha han hasta hay la las le les lo los mas
me mi muy ni no nos o otra otro para pero por porque que quien se ser si sin sobre son su sus tambien
tiene tras un una uno unos y ya año años dia dias segun ser fue sera dijo afirmo aseguro hoy ayer nuevo
nueva nuevos nuevas cada todo todos toda todas sus esto asi tras luego mientras
""".split())

# Same entity, different language/spelling -> one key (helps cross-language grouping).
ALIASES = {
    "eeuu": "usa", "ee.uu": "usa", "ee.uu.": "usa", "estados unidos": "usa", "united states": "usa",
    "us": "usa", "u.s.": "usa", "america": "usa", "washington": "usa",
    "reino unido": "uk", "britain": "uk", "united kingdom": "uk", "uk": "uk",
    "ucrania": "ukraine", "rusia": "russia", "alemania": "germany", "francia": "france",
    "espana": "spain", "italia": "italy", "japon": "japan", "brasil": "brazil", "mexico": "mexico",
    "union europea": "eu", "european union": "eu", "ue": "eu", "eu": "eu",
    "naciones unidas": "un", "united nations": "un", "onu": "un",
    "otan": "nato", "nato": "nato", "corea del norte": "north korea", "corea del sur": "south korea",
    "papa": "pope", "vaticano": "vatican", "turquia": "turkey", "siria": "syria", "libano": "lebanon",
    "egipto": "egypt", "catar": "qatar", "arabia saudita": "saudi arabia", "fmi": "imf", "imf": "imf",
    "casa blanca": "white house", "white house": "white house",
}
MULTIWORD_ALIASES = sorted((k for k in ALIASES if " " in k), key=len, reverse=True)

TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")
CAPWORD_RE = re.compile(r"\b(?:[A-ZÁÉÍÓÚÑÜ][\wáéíóúñü'\-]*(?:\.[A-Z]+\.?)?|\d[\d.,%]*)")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(s: str) -> str:
    return strip_accents(s).lower()


def clean_html(s: str) -> str:
    s = TAG_RE.sub(" ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:.-") + "…"


def stem(word: str) -> str:
    # Crude, but language-agnostic and good enough for headline matching:
    # "inflation"/"inflacion" -> "infla", "elections"/"election" -> "elect".
    return word[:5] if len(word) > 5 else word


def tokens(s: str) -> set[str]:
    words = WORD_RE.findall(normalize(s))
    return {stem(w) for w in words if w not in STOPWORDS and len(w) > 2}


ENTITY_STOP = set("""
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december breaking live update updates watch video exclusive
""".split())


def _known_proper() -> set[str]:
    from .lexicon import COUNTRY_KEYWORDS, TOPIC_KEYWORDS

    words = set(ALIASES) | set(ALIASES.values())
    for group in [*COUNTRY_KEYWORDS.values(), TOPIC_KEYWORDS["world"], TOPIC_KEYWORDS["latam"]]:
        words.update(w for w in group if " " not in w)
    return words


KNOWN_PROPER: set[str] = set()


def _num(key: str) -> str:
    # "1,1%" (es) and "1.1%" (en) are the same figure.
    return key.replace(",", ".") if key[:1].isdigit() else key


def entities(title: str, context: str = "") -> set[str]:
    """Proper nouns / figures in a headline, normalized and aliased across languages.

    `context` (e.g. the summary) helps decide whether the headline's first word,
    which is capitalised anyway, is really a name.
    """
    if not KNOWN_PROPER:
        KNOWN_PROPER.update(_known_proper())
    norm = normalize(title)
    found: set[str] = set()
    for phrase in MULTIWORD_ALIASES:
        if re.search(rf"\b{re.escape(phrase)}\b", norm):
            found.add(ALIASES[phrase])
    first = title.split(" ", 1)[0] if title else ""
    for w in CAPWORD_RE.findall(title):
        key = _num(normalize(w).strip(".,:;'-"))
        if not key or key in STOPWORDS or key in ENTITY_STOP or len(key) < 2:
            continue
        if w == first and not w.isupper() and key not in KNOWN_PROPER and not re.search(rf"(?<!^)(?<![.!?] )\b{re.escape(w)}\b", context):
            continue
        if key.replace(".", "").replace("%", "").isdigit() and len(key) < 3:
            continue  # small numbers are too common to identify a story
        found.add(ALIASES.get(key, key))
    return found


def contains_any(text_norm: str, phrases: list[str]) -> list[str]:
    """Which phrases (already normalized) occur as whole words in text_norm."""
    hits = []
    for p in phrases:
        if re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", text_norm):
            hits.append(p)
    return hits
