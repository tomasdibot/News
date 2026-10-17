"""Música: which stories come first (your artists, shows, releases) and how many outlets confirm a story."""

from __future__ import annotations

import re

from .cluster import Story
from .text import normalize

MAX_ARTISTS = 20   # your artists: searched, saved and ordered with the same cap everywhere

SHOW_WORDS = ["gira", "giras", "tour", "tours", "show", "shows", "recital", "recitales", "concierto", "conciertos",
              "estadio", "festival", "festivales", "line up", "lineup", "grilla", "lollapalooza", "cosquin rock",
              "primavera sound", "entradas"]
DATE_WORDS = ["fecha", "fechas"]   # "fecha de cobro" is not a show: a date counts only with a music context
DATE_CONTEXT = ["cantante", "artista", "cantautor", "rapero", "dj", "preventa", "sold out", "en obras",
                "en river", "en velez", "en el campo de polo"]
VENUE_WORDS = ["en el teatro", "teatro opera", "teatro coliseo", "teatro colon", "gran rex", "vorterix",
               "niceto", "luna park", "movistar arena", "hipodromo"]   # named venues count on their own; a bare "teatro" is often a play
RELEASE_WORDS = ["lanzamiento", "lanzamientos", "lanza", "nuevo album", "nuevo disco", "nuevo single", "estrena",
                 "album", "single"]


def _tokens(text: str) -> str:
    """Lowercase words only, so a whole-word match is a plain substring match on ' ' + text + ' '."""
    return " " + " ".join(w for w in re.split(r"[^a-z0-9]+", normalize(text or "")) if w) + " "


def _has(text: str, words: list[str]) -> bool:
    return any(" " + _tokens(w).strip() + " " in text for w in words)


def _headlines(story: Story) -> str:
    return _tokens(" . ".join(a.title for a in story.articles))


def artist_rank(story: Story, artists: list[str]) -> int | None:
    """Position in your artists list of the first artist named in any of the story's headlines."""
    text = _headlines(story)
    for i, name in enumerate(artists):
        if name.strip() and _has(text, [name]):
            return i
    return None


def music_tier(story: Story, rank: int | None) -> int:
    """0 your artist, 1 a show in Argentina or a big tour, 2 a release, 3 the rest."""
    if rank is not None:
        return 0
    text = _headlines(story)
    if _has(text, SHOW_WORDS + VENUE_WORDS):   # a place alone ("álbum en Argentina") is not a show
        return 1
    if _has(text, DATE_WORDS) and _has(text, DATE_CONTEXT):
        return 1
    if _has(text, RELEASE_WORDS):
        return 2
    return 3


def min_outlets(label: str) -> int:
    """Outlets that confirm a story in this theme: 2 for music and AI themes, 3 for the rest."""
    key = _tokens(label)
    if any(w in key for w in (" musica ", " music ", " ia ", " ai ", " inteligencia artificial ")):
        return 2
    return 3
