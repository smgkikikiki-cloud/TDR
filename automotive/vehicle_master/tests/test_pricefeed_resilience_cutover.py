"""Regression tests for the final Vehicle Master -> TDR pricefeed cutover delta."""

import unittest
import unittest.mock

from vehreg import pricefeed as pf
from tools import pricefeed_harvest as harvest_mod


def _source(source_id: str, url: str):
    return pf.Source(
        id=source_id,
        name=source_id,
        tier=pf.Tier("B"),
        adapter="wordpress",
        base_url=url,
    )


class PricefeedResilienceCutoverTests(unittest.TestCase):
    def setUp(self):
        self.sources = [
            _source("outlet_a", "https://good.example.test"),
            _source("outlet_b", "https://dead.example.test"),
        ]
        self.enterContext(unittest.mock.patch.object(
            harvest_mod.robots_check, "audit", return_value={}))
        self.enterContext(unittest.mock.patch.object(
            harvest_mod.robots_check, "verdict", return_value="allowed"))
        self.enterContext(unittest.mock.patch.object(
            harvest_mod, "identify", return_value=("Suzuki", "Fronx")))
        self.enterContext(unittest.mock.patch.object(
            harvest_mod, "extract_claims", return_value=[object()]))
        self.enterContext(unittest.mock.patch.object(
            harvest_mod, "to_dict", side_effect=lambda _: {"ok": True}))

    @staticmethod
    def _post(base_url: str):
        return {
            "id": 1,
            "title": {"rendered": "Suzuki Fronx ราคา 599,000"},
            "date_gmt": "2026-09-09T00:00:00",
            "modified_gmt": "2026-09-09T00:00:00",
            "link": f"{base_url}/1",
        }

    def test_dead_source_does_not_discard_successful_sources(self):
        def list_posts(base_url, **_):
            if "dead" in base_url:
                raise harvest_mod.HarvestError("certificate verify failed")
            return [self._post(base_url)]

        with unittest.mock.patch.object(harvest_mod, "list_posts", list_posts), \
             unittest.mock.patch.object(
                 harvest_mod,
                 "fetch_content",
                 return_value={
                     "content": {"rendered": "body"},
                     "link": "https://good.example.test/1",
                     "date_gmt": "2026-09-09T00:00:00",
                     "modified_gmt": "2026-09-09T00:00:00",
                 },
             ):
            batch = harvest_mod.harvest(
                self.sources, since="2026-09-01", catalog=object(), delay=0)

        self.assertEqual(1, len(batch["documents"]))
        self.assertEqual(["outlet_b"], batch["failed_sources"])
        self.assertEqual(1, batch["skipped"]["source_unreachable"])

    def test_single_post_fetch_failure_is_local_not_fatal(self):
        def list_posts(base_url, **_):
            return [self._post(base_url)]

        def fetch_content(base_url, _post_id):
            if "dead" in base_url:
                raise harvest_mod.HarvestError("timeout")
            return {
                "content": {"rendered": "body"},
                "link": f"{base_url}/1",
                "date_gmt": "2026-09-09T00:00:00",
                "modified_gmt": "2026-09-09T00:00:00",
            }

        with unittest.mock.patch.object(harvest_mod, "list_posts", list_posts), \
             unittest.mock.patch.object(harvest_mod, "fetch_content", fetch_content):
            batch = harvest_mod.harvest(
                self.sources, since="2026-09-01", catalog=object(), delay=0)

        self.assertEqual(1, len(batch["documents"]))
        self.assertEqual([], batch["failed_sources"])
        self.assertEqual(1, batch["skipped"]["source_unreachable"])


if __name__ == "__main__":
    unittest.main()
