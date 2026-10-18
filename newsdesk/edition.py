"""Build one edition: fetch -> cluster -> rank -> images -> HTML + JSON."""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, PackageLoader, select_autoescape

from .cluster import Story, cluster
from .config import ROOT, load_sources
from .fetch import fetch_all, fetch_og_image
from .lexicon import COUNTRY_NAMES, LOCK_UI, UI
from .lock import encrypt, password_from_env, site_salt
from .artists import fetch_google_news
from .music import MAX_ARTISTS, artist_rank, min_outlets, music_tier
from .econdata import fetch_econ
from .judge import candidates, configured_artists, configured_themes, judge_themes, set_reader, theme_key
from .neutral import neutralize
from .push import public_key_b64
from .lexicon import CONCEPTS, COUNTRY_KEYWORDS, SUGGESTED_THEMES, TOPIC_ALIASES, TOPIC_KEYWORDS
from .text import normalize
from .rank import score_stories, select_pool, select_sections
from .text import clean_headline, truncate

log = logging.getLogger(__name__)
SITE_DIR = ROOT / "site"            # published
STATIC_DIR = Path(__file__).parent / "static"
DATA_PATH = ROOT / "build" / "edition.json"  # never published: used by `notify`


def fill_missing_images(stories: list[Story], limit: int = 40) -> None:
    missing = [s for s in stories if not s.image][:limit]

    def find(s: Story):
        for a in [s.headline] + [a for a in s.articles if a is not s.headline]:
            img = fetch_og_image(a.link)
            if img:
                return img
        return None

    with cf.ThreadPoolExecutor(10) as pool:
        for s, img in zip(missing, pool.map(find, missing)):
            s.image = img


LEFT_SIDE = {"left", "center-left"}
RIGHT_SIDE = {"center-right", "right"}
SOFT_TOPICS = {"entertainment", "lifestyle"}


def ar_leans(s: Story) -> dict[str, str]:
    """Lean per Argentine outlet; foreign outlets are left out (the lean bar only covers AR)."""
    leans: dict[str, str] = {}
    for a in s.sources_for_display():   # only outlets shown for the story count
        if a.source.region.upper() == "AR":
            leans.setdefault(a.outlet, a.source.lean)
    return leans


def blindspot(s: Story) -> str | None:
    """"left" or "right": the side of the lean bar that has no Argentine outlet on a local story."""
    if not s.local or s.topic in SOFT_TOPICS:
        return None
    leans = ar_leans(s)
    if len(leans) < 3 or sum(1 for v in leans.values() if v) < 2:
        return None
    left = any(v in LEFT_SIDE for v in leans.values())
    right = any(v in RIGHT_SIDE for v in leans.values())
    if right and not left:
        return "left"
    if left and not right:
        return "right"
    return None


def log_multi_outlet_sample(multi: list[Story], n: int = 8) -> None:
    """Log a few multi-outlet headlines (public) so wrong merges can be judged from the run log:
    up to `n` local ones, then up to 5 from elsewhere."""
    local = [s for s in multi if s.local]
    rest = [s for s in multi if not s.local]
    picked = sorted(local, key=lambda s: len(ar_leans(s)), reverse=True)[:n] + rest[:5]
    for s in picked:
        who = "; ".join(f"{a.outlet}({a.source.lean or '?'}): {a.title}" for a in s.sources_for_display())
        log.info("multi-outlet sample: %s | %s", s.headline.title, who)


def story_dict(s: Story, ui_lang: str, artists: list[str] | None = None) -> dict:
    h = s.headline
    rank = artist_rank(s, artists or [])
    summary = h.summary or next((a.summary for a in s.articles if a.summary and a.source.lang == h.source.lang), "")
    if s.neutral:
        summary = s.neutral["summary"]
    return {
        "title": s.neutral["title"] if s.neutral else clean_headline(h.title),
        "summary": truncate(summary, 280),
        "ai": bool(s.neutral),
        "link": h.link,
        "image": s.image,
        "topic": s.topic,
        "published": s.latest.isoformat(),
        "outlets": s.outlets,
        "local": s.local,
        "blind": blindspot(s),
        "artist": rank,                    # position in your artists, None if none is named
        "mtier": music_tier(s, rank),      # 0 your artist, 1 show/tour, 2 release, 3 other
        "topics": {k: round(v, 2) for k, v in s.topic_scores.items() if v >= 0.2},
        "base": round(s.base, 4),
        "fixed": round(s.fixed, 3),
        "hype": bool(s.hype),
        "official": any(a.source.tier == "official" for a in s.articles),
        "fits": {k: 2 if v is None else int(v) for k, v in s.fits.items()},   # 2 = not read yet
        "score": round(s.score, 3),
        "sources": [
            {"outlet": a.outlet, "title": truncate(a.title, 160), "link": a.link, "lang": a.source.lang,
             "lean": a.source.lean}
            for a in s.sources_for_display()
        ],
    }


def build_edition(cfg: dict, articles=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ui_lang = cfg["site"]["ui_language"]
    artists = configured_artists(cfg)
    if articles is None:
        articles = fetch_all(load_sources(cfg), country=cfg["profile"]["country"])
        articles += fetch_google_news(artists, now)
    stories = score_stories(cluster(articles), cfg, now)
    sections = select_sections(stories, cfg)  # what the morning notification uses
    pool = select_pool(stories, cfg)            # what the app shows and re-ranks
    # Your own themes (NEWSDESK_THEMES) always get their best candidates in, even niche ones.
    set_reader(cfg)
    seen = {id(s) for s in pool}
    for theme in configured_themes(cfg):
        for s in candidates(theme, stories)[:25]:
            if id(s) not in seen:
                seen.add(id(s))
                pool.append(s)
    pool.sort(key=lambda s: s.score, reverse=True)
    # Read themes first, so neutral titles go first to the stories you will actually see.
    judged = judge_themes(pool, cfg) if articles else []
    if articles and (cfg.get("neutral_titles") or {}).get("enabled", True):
        neutralize(pool, cfg)
    if articles and cfg.get("_fetch_images", True):
        fill_missing_images(pool, limit=90)

    econ = []
    if cfg["profile"]["country"] == "AR":
        econ = fetch_econ(now)
        log.info("econ data: %d/4", len(econ))

    multi = [s for s in stories if s.local and len(ar_leans(s)) >= 3]
    flags = [blindspot(s) for s in multi]
    log.info("blindspot: %d flagged (left_ignores=%d, right_ignores=%d) of %d local multi-outlet stories",
             sum(1 for f in flags if f), flags.count("left"), flags.count("right"), len(multi))
    log_multi_outlet_sample(multi + [s for s in stories if not s.local and len(s.outlets) >= 2])

    tz = ZoneInfo(cfg["notification"]["timezone"])
    return {
        "generated_at": now.isoformat(),
        "generated_local": now.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
        "article_count": len(articles),
        "outlet_count": len({a.outlet for a in articles}),
        "top": [story_dict(s, ui_lang, artists) for s in sections["top"]],
        "local": [story_dict(s, ui_lang, artists) for s in sections["local"]],
        "stories": [story_dict(s, ui_lang, artists) for s in pool],
        "themes": theme_dictionary(cfg),
        "econ": econ,       # official numbers for Argentina (econdata.py)
        "judged": judged,   # themes the AI filter knows (NEWSDESK_THEMES)
    }


def theme_dictionary(cfg: dict) -> dict:
    """What the app needs to turn themes typed by the user into sections."""
    lang = cfg["site"]["ui_language"]
    labels = UI.get(lang, UI["en"])["topics"]
    concepts = [
        {"id": t, "label": labels.get(t, t), "topic": t,
         "names": [a.replace("-", " ") for a in TOPIC_ALIASES.get(t, "").split()] + [normalize(labels.get(t, t))],
         "keywords": []}
        for t in TOPIC_KEYWORDS
    ]
    # Custom topics from config.yaml are themes too.
    for t in cfg["profile"]["topics"]:
        if t.get("keywords") and t["name"] not in TOPIC_KEYWORDS:
            concepts.append({"id": t["name"], "label": t["name"], "topic": t["name"],
                             "names": [normalize(t["name"])], "keywords": [normalize(k) for k in t["keywords"]]})
    for c in CONCEPTS:
        concepts.append({"id": c["id"], "label": c["label"].get(lang, c["label"]["en"]), "topic": c["topic"],
                         "short": (c.get("short") or {}).get(lang, ""),
                         "names": c["names"], "keywords": c["keywords"], "must": c.get("must", []),
                         "not": c.get("not", []), "strict": c.get("strict", False)})
    by_id = {c["id"]: c["label"] for c in concepts}
    # Outlets that confirm a story, per theme (built-in labels and your own): 2 for music and AI, else 3.
    need = {theme_key(l): min_outlets(l) for l in list(by_id.values()) + configured_themes(cfg)}
    country = cfg["profile"]["country"]
    return {
        "concepts": concepts,
        "min_outlets": need,
        "max_artists": MAX_ARTISTS,
        "suggested": [by_id[i] for i in SUGGESTED_THEMES if i in by_id],
        "all": sorted(set(by_id.values()), key=lambda l: normalize(l)),
        # Typing your country as (part of) a theme means "news about it".
        "country_names": sorted({normalize(n) for names in COUNTRY_NAMES.values() for code, n in names.items()
                                 if code == country} | set(COUNTRY_KEYWORDS.get(country, [])[:4])),
        # Not news people usually want unless they ask for it.
        "soft_topics": ["entertainment", "lifestyle"],
    }


def render(edition: dict, cfg: dict, out_dir: Path = SITE_DIR, data_path: Path = DATA_PATH,
           password: str | None = None) -> Path:
    """Write the site. With a password (argument or NEWSDESK_PASSWORD) the page is encrypted."""
    password = password or password_from_env()
    lang = cfg["site"]["ui_language"]
    ui = UI.get(lang, UI["en"])
    env = Environment(loader=PackageLoader("newsdesk", "templates"), autoescape=select_autoescape())
    env.filters["topic_label"] = lambda name: ui["topics"].get(name, (name or "").replace("_", " ").title())
    html = env.get_template("index.html").render(
        e=edition,
        ui=ui,
        lang=lang,
        cfg=cfg,
        push_key=public_key_b64(cfg),
        repo=os.environ.get("GITHUB_REPOSITORY", ""),
        ref=os.environ.get("GITHUB_REF_NAME", ""),
        country_name=COUNTRY_NAMES.get(lang, {}).get(cfg["profile"]["country"], cfg["profile"]["country"]),
    )
    if password:
        html = env.get_template("lock.html").render(
            title=cfg["site"]["title"],
            cfg=cfg,
            lang=lang,
            t=LOCK_UI.get(lang, LOCK_UI["en"]),
            payload=encrypt(html, password, site_salt(cfg)),
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    write_app_files(env, cfg, out_dir)
    (out_dir / "edition.json").unlink(missing_ok=True)  # left over from older versions: would leak the news
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(edition, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir / "index.html"


def write_app_files(env: Environment, cfg: dict, out_dir: Path) -> None:
    """Files that let the site be installed on a phone's home screen and open offline."""
    for icon in STATIC_DIR.glob("*.png"):
        shutil.copyfile(icon, out_dir / icon.name)
    title = cfg["site"]["title"]
    manifest = {
        "name": title,
        "short_name": title[:12],
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#f7f5f0",
        "theme_color": "#9b2c2c",
        "lang": cfg["site"]["ui_language"],
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    (out_dir / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    # A new cache name per build makes phones drop the previous edition's shell.
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    (out_dir / "sw.js").write_text(env.get_template("sw.js").render(version=version), encoding="utf-8")
