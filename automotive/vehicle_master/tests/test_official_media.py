from dataclasses import replace

from vehreg.official_media.adapters import SOURCES
from vehreg.official_media.models import ImageSlot, OfficialSource, ReviewStatus, SourceType, VehicleIdentity
from vehreg.official_media.parsing import parse_page
from vehreg.official_media.pipeline import _crawlable_page, _safe_url, select_canonical
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


def test_brochure_links_are_not_crawl_pages_and_spaces_are_encoded():
    raw = "https://www.honda.co.th/assets/New Accord e:HEV leaflet .pdf?download=New Accord.pdf"
    safe = _safe_url(raw)
    assert " " not in safe
    assert "%20" in safe
    assert not _crawlable_page(safe)
    assert _crawlable_page("https://www.honda.co.th/accord")


def test_scoring_auto_approves_strong_official_candidate():
    source = SOURCES["honda"]
    html = """<title>Honda Civic FE official model</title>
    <img src="/assets/civic-fe-front-3q.jpg" alt="Honda Civic FE front 3q" width="2000">"""
    images, _, _ = parse_page(html, "https://www.honda.co.th/civic", SourceType.OFFICIAL_SITE)
    candidate = score_candidate(images[0], IDENTITY, source)
    assert candidate.score >= 85
    assert candidate.status is ReviewStatus.APPROVED
    assert candidate.slot is ImageSlot.FRONT_3Q


def test_model_tokens_allow_separator_variants_without_prefix_collisions():
    byd = SOURCES["byd"]
    seal = VehicleIdentity(
        brand_id="byd",
        model_id="byd.seal",
        generation_id="byd.seal.seal",
        model_name="Seal",
        generation_code="",
        model_year=2026,
    )
    html = """<title>BYD Seal</title>
    <img src="https://www.byd.com/material/__CN/byd-site/th/home/model/sealion5dmi-2.png">
    <img src="https://www.byd.com/material/__CN/byd-site/th/home/model/seal.png">"""
    images, _, _ = parse_page(html, "https://www.byd.com/en-th/car/seal", SourceType.OFFICIAL_SITE)
    scored = [score_candidate(item, seal, byd) for item in images]
    by_url = {item.image_url: item for item in scored}
    wrong = next(item for url, item in by_url.items() if "sealion5dmi" in url)
    right = next(item for url, item in by_url.items() if url.endswith("/seal.png"))
    assert not wrong.identity_evidence
    assert right.identity_evidence

    crv = VehicleIdentity(
        brand_id="honda",
        model_id="honda.crv",
        generation_id="honda.crv.rs",
        model_name="CR-V",
        generation_code="RS",
        model_year=2026,
    )
    assert link_score("https://www.honda.co.th/crv", "", crv, SOURCES["honda"]) > 0

    atto3 = VehicleIdentity(
        brand_id="byd",
        model_id="byd.atto3",
        generation_id="byd.atto3.atto3",
        model_name="Atto 3",
        generation_code="",
        model_year=2026,
    )
    assert link_score("https://www.byd.com/en-th/car/atto3", "", atto3, byd) > 0


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


def test_bmw_extensionless_cosy_image_is_kept_and_classified_as_exterior():
    source = OfficialSource(
        brand_id="bmw",
        seed_urls=("https://www.bmw.co.th/en/all-models.html",),
        allowed_hosts=("bmw.co.th",),
    )
    identity = VehicleIdentity(
        brand_id="bmw",
        model_id="bmw.x3",
        generation_id="bmw.bmw_x3.g45",
        model_name="X3",
        generation_code="G45",
        model_year=2026,
    )
    cosy = "https://prod.cosy.bmw.cloud/bmwweb/cosySec?COSY-EU-100-7331c9Nv2Z7d5c1Q"
    html = f'''<title>BMW X3</title><img src="{cosy}" alt="BMW X3 20d xDrive M Sport Pro">'''
    images, _, _ = parse_page(
        html,
        "https://www.bmw.co.th/en/all-models/x-series/x3/bmw-x3.html",
        SourceType.OFFICIAL_SITE,
    )
    assert len(images) == 1
    candidate = score_candidate(images[0], identity, source)
    assert candidate.identity_evidence
    assert candidate.slot is ImageSlot.FRONT_3Q
    assert candidate.status is ReviewStatus.APPROVED


def test_unknown_extensionless_host_is_not_treated_as_image():
    html = '<title>BMW X3</title><img src="https://example.invalid/render?id=x3" alt="BMW X3">'
    images, _, _ = parse_page(
        html,
        "https://www.bmw.co.th/en/all-models/x-series/x3/bmw-x3.html",
        SourceType.OFFICIAL_SITE,
    )
    assert images == []
