from dataclasses import replace

from vehreg.official_media.adapters import SOURCES
from vehreg.official_media.models import ImageSlot, ReviewStatus, SourceType, VehicleIdentity
from vehreg.official_media.parsing import parse_page
from vehreg.official_media.pipeline import select_canonical
from vehreg.official_media.scoring import link_score, score_candidate

IDENTITY = VehicleIdentity(
    brand_id="honda",
    model_id="honda.civic",
    generation_id="honda.civic.fe",
    model_name="Civic",
    generation_code="FE",
    model_year=2026,
)


def test_parser_prefers_largest_srcset_and_og_image():
    html = """<html><head><title>Honda Civic</title>
    <meta property="og:image" content="/hero/civic-fe.jpg"></head>
    <body><img alt="Civic front 3q" src="/small.jpg"
      srcset="/civic-800.jpg 800w, /civic-2000.jpg 2000w" width="2000"></body></html>"""
    images, _, title = parse_page(html, "https://www.honda.co.th/civic", SourceType.OFFICIAL_SITE)
    assert title == "Honda Civic"
    assert any(item.is_og_image for item in images)
    assert any(item.image_url.endswith("civic-2000.jpg") for item in images)


def test_off_domain_links_are_never_crawled():
    source = SOURCES["honda"]
    assert link_score("https://example.invalid/honda/civic", "Civic", IDENTITY, source) < 0
    assert link_score("https://www.honda.co.th/civic", "Civic", IDENTITY, source) > 0


def test_scoring_auto_approves_strong_official_candidate():
    source = SOURCES["honda"]
    html = """<title>Honda Civic FE official model</title>
    <img src="/assets/civic-fe-front-3q.jpg" alt="Honda Civic FE front 3q" width="2000">"""
    images, _, _ = parse_page(html, "https://www.honda.co.th/civic", SourceType.OFFICIAL_SITE)
    candidate = score_candidate(images[0], IDENTITY, source)
    assert candidate.score >= 85
    assert candidate.status is ReviewStatus.APPROVED
    assert candidate.slot is ImageSlot.FRONT_3Q


def test_generation_visual_key_gives_trim_inheritance():
    assert IDENTITY.visual_key == "honda.civic.fe"


def test_canonical_set_keeps_one_per_slot():
    source = SOURCES["honda"]
    html = """<title>Honda Civic FE</title>
    <img src="/civic-fe-front-3q.jpg" alt="Civic FE front 3q" width="2000">
    <img src="/civic-fe-side.jpg" alt="Civic FE side" width="2000">"""
    images, _, _ = parse_page(html, "https://www.honda.co.th/civic", SourceType.OFFICIAL_SITE)
    selected = select_canonical(score_candidate(item, IDENTITY, source) for item in images)
    assert any(item.slot is ImageSlot.FRONT_3Q for item in selected)
    assert any(item.slot is ImageSlot.SIDE for item in selected)
