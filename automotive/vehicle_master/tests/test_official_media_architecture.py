from vehreg.official_media.adapters import MODEL_PAGE_HINTS, SOURCES
from vehreg.official_media.models import ImageSlot, ReviewStatus, SourceType, VehicleIdentity
from vehreg.official_media.parsing import parse_page
from vehreg.official_media.scoring import score_candidate


def test_legacy_background_attributes_and_css_are_image_candidates():
    identity = VehicleIdentity(
        brand_id="gwm",
        model_id="gwm.haval_jolion",
        generation_id="gwm.haval_jolion.jol",
        model_name="Haval Jolion",
        generation_code="JOL",
        model_year=2026,
    )
    html = '''<html><head><title>GWM Thailand - HAVAL JOLION</title></head><body>
    <div aria-label="HAVAL JOLION exterior"
         data-background="/content/dam/gwm/pages/th/en/model/haval-jolion/360/haval-jolion-white.png"></div>
    <div title="HAVAL JOLION profile"
         style="background-image: url('/content/dam/gwm/pages/th/en/model/haval-jolion/haval-jolion-side.webp')"></div>
    </body></html>'''
    images, _, _ = parse_page(
        html,
        "https://www1.gwm.co.th/HAVAL_JOLION.html",
        SourceType.OFFICIAL_SITE,
    )
    urls = {item.image_url for item in images}
    assert "https://www1.gwm.co.th/content/dam/gwm/pages/th/en/model/haval-jolion/360/haval-jolion-white.png" in urls
    assert "https://www1.gwm.co.th/content/dam/gwm/pages/th/en/model/haval-jolion/haval-jolion-side.webp" in urls

    exterior = next(item for item in images if "/360/" in item.image_url)
    scored = score_candidate(exterior, identity, SOURCES["gwm"])
    assert scored.identity_evidence
    assert scored.slot is ImageSlot.FRONT_3Q
    assert scored.status is ReviewStatus.APPROVED


def test_curated_shared_family_page_never_replaces_asset_identity_evidence():
    identity = VehicleIdentity(
        brand_id="toyota",
        model_id="toyota.vellfire",
        generation_id="toyota.vellfire.gen1",
        model_name="Vellfire",
        generation_code="",
        model_year=2026,
    )
    page = "https://www.toyota.co.th/model/alphard"
    previous = MODEL_PAGE_HINTS.get(identity.generation_id)
    MODEL_PAGE_HINTS[identity.generation_id] = (page,)
    try:
        html = '''<title>Toyota Alphard</title>
        <img src="/media/product/series/grades/v/alphard/34/vellfire.webp"
             alt="Alphard Vellfire HEV Premium">'''
        images, _, _ = parse_page(html, page, SourceType.OFFICIAL_SITE)
        candidate = score_candidate(images[0], identity, SOURCES["toyota"])
        assert candidate.identity_evidence
        assert candidate.slot is ImageSlot.FRONT_3Q
        assert candidate.score >= 85
        assert "+15 curated model-page provenance" in candidate.score_reasons
        assert candidate.status is ReviewStatus.APPROVED

        wrong_html = '''<title>Toyota Alphard</title>
        <img src="/media/product/series/grades/v/alphard/35/alphard.webp"
             alt="Alphard HEV Premium">'''
        wrong, _, _ = parse_page(wrong_html, page, SourceType.OFFICIAL_SITE)
        rejected = score_candidate(wrong[0], identity, SOURCES["toyota"])
        assert not rejected.identity_evidence
        assert "+15 curated model-page provenance" not in rejected.score_reasons
        assert rejected.status is not ReviewStatus.APPROVED
    finally:
        if previous is None:
            MODEL_PAGE_HINTS.pop(identity.generation_id, None)
        else:
            MODEL_PAGE_HINTS[identity.generation_id] = previous
