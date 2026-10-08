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
from .push import public_key_b64
from .rank import score_stories, select_sections
from .text import truncate

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


def story_dict(s: Story, ui_lang: str) -> dict:
    h = s.headline
    summary = h.summary or next((a.summary for a in s.articles if a.summary and a.source.lang == h.source.lang), "")
    return {
        "title": h.title,
        "summary": truncate(summary, 320),
        "link": h.link,
        "image": s.image,
        "topic": s.topic,
        "published": s.latest.isoformat(),
        "outlets": s.outlets,
        "local": s.local,
        "reasons": s.reasons,
        "score": round(s.score, 3),
        "sources": [
            {"outlet": a.outlet, "title": a.title, "link": a.link, "lang": a.source.lang}
            for a in s.sources_for_display()
        ],
    }


def build_edition(cfg: dict, articles=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ui_lang = cfg["site"]["ui_language"]
    if articles is None:
        articles = fetch_all(load_sources(cfg))
    stories = score_stories(cluster(articles), cfg, now)
    sections = select_sections(stories, cfg)

    shown = sections["top"] + sections["local"] + [s for _, items in sections["topics"] for s in items]
    if articles and cfg.get("_fetch_images", True):
        fill_missing_images(shown)

    tz = ZoneInfo(cfg["notification"]["timezone"])
    return {
        "generated_at": now.isoformat(),
        "generated_local": now.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
        "article_count": len(articles),
        "outlet_count": len({a.outlet for a in articles}),
        "top": [story_dict(s, ui_lang) for s in sections["top"]],
        "local": [story_dict(s, ui_lang) for s in sections["local"]],
        "topics": [
            {"name": name, "stories": [story_dict(s, ui_lang) for s in items]}
            for name, items in sections["topics"]
        ],
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
