from datetime import timedelta

from conftest import NOW
from newsdesk.cluster import Story
from newsdesk.config import Source
from newsdesk.edition import blindspot, build_edition, story_dict
from newsdesk.fetch import Article


def make_story(leans, local=True, topic="economy", regions=None):
    """leans: one entry per article; (name, lean) pairs share an outlet when the name repeats."""
    arts = []
    for i, (name, lean) in enumerate(leans):
        src = Source(id=f"{name}{i}", outlet=name, url="x", lang="es", region=(regions or {}).get(name, "AR"), lean=lean)
        arts.append(Article(source=src, title=f"t{i}", link=f"https://x/{i}", summary="",
                            published=NOW - timedelta(hours=10 - i)))
    s = Story(articles=arts, local=local, topic=topic)
    s.headline = arts[0]
    return s


def test_all_centre_has_no_blindspot():
    assert blindspot(make_story([("A", "center"), ("B", "center"), ("C", "center")])) is None


def test_fewer_than_three_outlets_is_not_flagged():
    assert blindspot(make_story([("A", "center"), ("B", "center-right")])) is None


def test_unknown_lean_is_never_a_side():
    s = make_story([("A", "center"), ("B", ""), ("C", "")])
    assert blindspot(s) is None            # only one known lean
    s = make_story([("A", "center"), ("B", "center-right"), ("C", "")])
    assert blindspot(s) == "left"


def test_both_sides_present_is_not_flagged():
    s = make_story([("A", "center"), ("B", "center-left"), ("C", "center-right")])
    assert blindspot(s) is None


def test_only_right_side_present_means_left_ignores():
    s = make_story([("A", "center"), ("B", "center-right"), ("C", "right")])
    assert blindspot(s) == "left"


def test_only_left_side_present_means_right_ignores():
    s = make_story([("A", "center"), ("B", "center-left"), ("C", "center")])
    assert blindspot(s) == "right"


def test_same_outlet_through_two_feeds_counts_once():
    s = make_story([("A", "center"), ("A", "center"), ("B", "center-right")])
    assert blindspot(s) is None            # two outlets only


def test_non_local_story_is_not_flagged():
    s = make_story([("A", "center"), ("B", "center-right"), ("C", "center")], local=False)
    assert blindspot(s) is None


def test_foreign_outlets_do_not_count_towards_a_local_blindspot():
    s = make_story([("BBC", "center"), ("DW", "center"), ("La Nación", "center-right")],
                   regions={"BBC": "global", "DW": "global"})
    assert blindspot(s) is None            # only one Argentine outlet


def test_soft_news_is_not_flagged():
    s = make_story([("A", "center"), ("B", "center-right"), ("C", "center")], topic="entertainment")
    assert blindspot(s) is None


def test_story_dict_carries_blind():
    s = make_story([("A", "center"), ("B", "center-right"), ("C", "center")])
    assert story_dict(s, "es")["blind"] == "left"
    s = make_story([("A", "center"), ("B", "center"), ("C", "center")])
    assert story_dict(s, "es")["blind"] is None


def test_build_logs_blindspot_summary(articles, cfg, caplog):
    with caplog.at_level("INFO", logger="newsdesk.edition"):
        build_edition(cfg, articles=articles, now=NOW)
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("blindspot: "))
    assert "flagged (left_ignores=" in line and "local multi-outlet stories" in line


def test_build_logs_multi_outlet_sample(caplog):
    import logging
    from newsdesk.edition import log_multi_outlet_sample
    s = make_story([("A", "center"), ("B", "center-right"), ("C", "")])
    with caplog.at_level(logging.INFO):
        log_multi_outlet_sample([s])
    assert "multi-outlet sample: t0 | A(center), B(center-right), C(?)" in caplog.text
