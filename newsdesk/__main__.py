"""Command line: python -m newsdesk {build,notify,serve,check-feeds}"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import logging
import sys

from .config import load_config, load_sources
from .edition import SITE_DIR, build_edition, render
from .notify import NotifyError, notify

log = logging.getLogger("newsdesk")


def cmd_build(cfg, args) -> int:
    edition = build_edition(cfg)
    path = render(edition, cfg)
    print(f"wrote {path} ({len(edition['top'])} top stories, {edition['article_count']} articles)")
    return 0


def cmd_notify(cfg, args) -> int:
    path = SITE_DIR / "edition.json"
    if args.fresh or not path.exists():
        edition = build_edition(cfg)
        render(edition, cfg)
    else:
        edition = json.loads(path.read_text(encoding="utf-8"))
    try:
        notify(edition, cfg, provider=args.provider)
    except NotifyError as exc:
        log.error("%s", exc)
        return 1
    return 0


def cmd_check_feeds(cfg, args) -> int:
    from .fetch import fetch_source

    sources = load_sources(cfg)
    bad = 0
    for s in sources:
        arts = fetch_source(s)
        with_img = sum(1 for a in arts if a.image)
        status = "OK " if arts else "ERR"
        bad += not arts
        print(f"{status} {s.id:18} {len(arts):4} articles  {with_img:4} with images  {s.url}")
    print(f"\n{len(sources) - bad}/{len(sources)} feeds working")
    return 0


def cmd_serve(cfg, args) -> int:
    """Self-hosted mode: rebuild on an interval, send WhatsApp at the configured time, serve the site."""
    from zoneinfo import ZoneInfo

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    def rebuild():
        try:
            render(build_edition(cfg), cfg)
            log.info("edition rebuilt")
        except Exception:
            log.exception("rebuild failed")

    def daily():
        try:
            edition = build_edition(cfg)
            render(edition, cfg)
            notify(edition, cfg)
        except Exception:
            log.exception("daily notification failed")

    rebuild()
    hour, minute = (int(x) for x in cfg["notification"]["time"].split(":"))
    tz = ZoneInfo(cfg["notification"]["timezone"])
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(rebuild, "interval", minutes=cfg["refresh_minutes"], id="refresh")
    sched.add_job(daily, CronTrigger(hour=hour, minute=minute, timezone=tz), id="notify", misfire_grace_time=3600)
    sched.start()
    log.info("refreshing every %s min; WhatsApp at %s %s", cfg["refresh_minutes"], cfg["notification"]["time"], tz)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer((args.host, args.port), handler)
    print(f"serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sched.shutdown(wait=False)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="newsdesk", description="Personal, low-bias news edition")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="fetch, rank and render the site into ./site")
    n = sub.add_parser("notify", help="send the WhatsApp summary of the current edition")
    n.add_argument("--provider", help="override notification.provider (callmebot, twilio, console)")
    n.add_argument("--fresh", action="store_true", help="rebuild the edition before sending")
    sub.add_parser("check-feeds", help="test every configured feed")
    s = sub.add_parser("serve", help="run continuously: refresh, notify daily and serve the site")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    return {"build": cmd_build, "notify": cmd_notify, "serve": cmd_serve, "check-feeds": cmd_check_feeds}[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
