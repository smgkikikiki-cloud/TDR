"""Phase 3 preflight fix: registration_observations_v2 must actually be
immutable. Same id + same payload = idempotent no-op; same id + different
payload = an explicit, surfaced drift blocker, never a silent "keep the
first"; and the whole-run apply gate never partially writes a disputed run."""

import unittest

from tests.test_resolution_v2 import _catalog, _resolver
from vehreg.ingest import ColumnMap
from vehreg.registration_observation import from_mapped_row
from vehreg.registration_v2_writer import (
    build_batch,
    plan_observation_writes,
    writes_to_apply,
)

_COLMAP = ColumnMap(period="p", brand="b", model="m", units="u")


def _row(period, brand, model, units, *, file_sha256="f", row_index=0):
    return from_mapped_row(
        {"p": period, "b": brand, "m": model, "u": str(units)},
        _COLMAP, file_sha256=file_sha256, row_index=row_index)


class WithinBatchDriftTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.resolver = _resolver(self.catalog)

    def test_identical_repeat_is_an_idempotent_no_op(self):
        a = _row("2026-01", "Acme", "Gecko", 10)
        b = _row("2026-01", "Acme", "Gecko", 10)   # same source_ref -> same id, same payload
        self.assertEqual(a.observation_id, b.observation_id)
        self.assertEqual(a.payload_hash, b.payload_hash)
        batch = build_batch([a, b], self.resolver, self.catalog)
        self.assertEqual(batch.drift_conflicts, [])
        self.assertEqual(len(batch.observation_rows), 1)
        self.assertEqual(len(batch.fact_rows), 1)

    def test_conflicting_payload_under_the_same_id_is_a_drift_conflict(self):
        a = _row("2026-01", "Acme", "Gecko", 10)
        b = _row("2026-01", "Acme", "Gecko", 999)   # same source_ref, different units
        self.assertEqual(a.observation_id, b.observation_id)
        self.assertNotEqual(a.payload_hash, b.payload_hash)
        batch = build_batch([a, b], self.resolver, self.catalog)
        self.assertEqual(len(batch.drift_conflicts), 1)
        conflict = batch.drift_conflicts[0]
        self.assertEqual(conflict.observation_id, a.observation_id)
        self.assertEqual(conflict.source, "within_batch")
        self.assertEqual(conflict.units, 10 + 999)
        # Neither occurrence is silently kept - the id produces no row at all.
        self.assertEqual(batch.observation_rows, [])
        self.assertEqual(batch.fact_rows, [])
        self.assertEqual(batch.resolutions, [])

    def test_drift_conflict_units_remain_visible_in_the_summary(self):
        a = _row("2026-01", "Acme", "Gecko", 10)
        b = _row("2026-01", "Acme", "Gecko", 999)
        clean = _row("2026-01", "Acme", "Ranger", 5, row_index=1)
        batch = build_batch([a, b, clean], self.resolver, self.catalog)
        summary = batch.summary()
        self.assertEqual(summary["drift_conflicts"], 1)
        self.assertEqual(summary["drift_conflict_units"], 1009)
        # The clean observation is unaffected by the unrelated conflict.
        self.assertEqual(summary["observations"], 1)
        self.assertTrue(batch.reconciles())


class ExistingDriftTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.resolver = _resolver(self.catalog)

    def test_same_id_same_persisted_hash_is_unchanged_not_reinserted(self):
        obs = _row("2026-01", "Acme", "Gecko", 10)
        batch = build_batch([obs], self.resolver, self.catalog)
        existing = {obs.observation_id: obs.payload_hash}
        plan = plan_observation_writes(batch, existing)
        self.assertEqual(plan.to_insert, [])
        self.assertEqual(plan.unchanged_ids, [obs.observation_id])
        self.assertEqual(plan.drift_conflicts, [])
        self.assertFalse(plan.is_blocked)

    def test_same_id_different_persisted_hash_is_a_drift_conflict(self):
        obs = _row("2026-01", "Acme", "Gecko", 10)
        batch = build_batch([obs], self.resolver, self.catalog)
        existing = {obs.observation_id: "a-completely-different-hash"}
        plan = plan_observation_writes(batch, existing)
        self.assertEqual(plan.to_insert, [])
        self.assertEqual(plan.unchanged_ids, [])
        self.assertEqual(len(plan.drift_conflicts), 1)
        self.assertEqual(plan.drift_conflicts[0].source, "existing")
        self.assertTrue(plan.is_blocked)

    def test_new_id_not_seen_before_is_a_plain_insert(self):
        obs = _row("2026-01", "Acme", "Gecko", 10)
        batch = build_batch([obs], self.resolver, self.catalog)
        plan = plan_observation_writes(batch, existing_payload_hashes={})
        self.assertEqual(len(plan.to_insert), 1)
        self.assertEqual(plan.to_insert[0]["observation_id"], obs.observation_id)
        self.assertFalse(plan.is_blocked)

    def test_omitted_existing_hashes_defaults_to_all_new(self):
        obs = _row("2026-01", "Acme", "Gecko", 10)
        batch = build_batch([obs], self.resolver, self.catalog)
        plan = plan_observation_writes(batch)
        self.assertEqual(len(plan.to_insert), 1)

    def test_within_batch_conflicts_are_carried_into_the_plan(self):
        a = _row("2026-01", "Acme", "Gecko", 10)
        b = _row("2026-01", "Acme", "Gecko", 999)
        batch = build_batch([a, b], self.resolver, self.catalog)
        plan = plan_observation_writes(batch, {})
        self.assertEqual(len(plan.drift_conflicts), 1)
        self.assertEqual(plan.drift_conflicts[0].source, "within_batch")
        self.assertTrue(plan.is_blocked)


class GlobalApplyGateTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.resolver = _resolver(self.catalog)

    def test_clean_plan_applies_everything(self):
        obs = _row("2026-01", "Acme", "Gecko", 10)
        batch = build_batch([obs], self.resolver, self.catalog)
        plan = plan_observation_writes(batch, {})
        applied = writes_to_apply(batch, plan)
        self.assertEqual(len(applied.observations), 1)
        self.assertEqual(len(applied.facts), 1)

    def test_any_drift_conflict_blocks_the_entire_run_even_clean_rows(self):
        conflicting_a = _row("2026-01", "Acme", "Gecko", 10)
        conflicting_b = _row("2026-01", "Acme", "Gecko", 999)
        clean = _row("2026-01", "Acme", "Ranger", 5, row_index=1)
        batch = build_batch([conflicting_a, conflicting_b, clean],
                           self.resolver, self.catalog)
        plan = plan_observation_writes(batch, {})
        self.assertTrue(plan.is_blocked)
        applied = writes_to_apply(batch, plan)
        # Nothing is written this run - not even the unrelated clean row.
        self.assertEqual(applied.observations, [])
        self.assertEqual(applied.facts, [])
        self.assertEqual(applied.reviews, [])

    def test_unchanged_ids_still_get_fact_review_upserts(self):
        # Facts/review rows are derived and may always be regenerated for an
        # id that is not in conflict, even when the observation itself is a
        # no-op this run (e.g. a resolver/catalog update changed the
        # resolution for an already-persisted observation).
        obs = _row("2026-01", "Acme", "Gecko", 10)
        batch = build_batch([obs], self.resolver, self.catalog)
        plan = plan_observation_writes(batch, {obs.observation_id: obs.payload_hash})
        applied = writes_to_apply(batch, plan)
        self.assertEqual(applied.observations, [])   # already persisted, no insert
        self.assertEqual(len(applied.facts), 1)       # but the fact still upserts


if __name__ == "__main__":
    unittest.main()
