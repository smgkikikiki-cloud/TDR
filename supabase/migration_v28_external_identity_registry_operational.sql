-- Phase 1 completion: make canonical_object_map's cardinality model
-- compatible with the Git-backed external identity registry.
--
-- See docs/vehicle-platform/EXTERNAL_IDENTITY_PERSISTENCE.md ("Key and
-- cardinality rules") and automotive/vehicle_master/tdr_bridge/
-- external_identity_registry.py. The registry deliberately permits
-- multiple external identities to bind to the same canonical target (two
-- legacy identities that both correctly identify the same car is a
-- legitimate, expected shape -- the registry's own key is
-- (namespace, external_entity_type, external_id, canonical_entity_type),
-- not a function of canonical_id).
--
-- canonical_object_map currently forbids that shape with a global partial
-- unique index:
--
--   create unique index canonical_object_map_verified_target_uq
--     on canonical_object_map (canonical_entity_type, canonical_id)
--     where status = 'verified';
--
-- That was a reasonable constraint when canonical_object_map was the only
-- write-authority gate and every canonical target was expected to have at
-- most one verified source. It now conflicts with the registry's model, so
-- it is dropped here rather than deferred to a future packet.
--
-- What this migration does NOT change, deliberately:
--   * No data is modified, inserted, or deleted -- dropping an index never
--     touches row data, so this is safe against current production data by
--     construction (a table with N rows respecting a UNIQUE index trivially
--     still respects "no such index").
--   * The source-key uniqueness constraint from migration_v12,
--     `unique (source_table, source_id, canonical_entity_type)`, is
--     untouched. That is the key the operational write gate
--     (lib/canonical-write-shadow.ts) and the registry-sync tool
--     (tools/sync_external_identity_registry.py) both actually query by;
--     removing the *target* index does not weaken it in any way.
--   * The per-row correctness check from migration_v12,
--     `(status = 'verified' and canonical_id is not null and verified_at is
--     not null) or status <> 'verified'`, is untouched.
--   * `lib/canonical-write-shadow.ts`'s query
--     (`.eq('source_table', ...).eq('source_id', ...).eq('canonical_entity_type', ...)`)
--     is answered entirely by the source-key index and does not reference
--     the dropped target index at all -- write-gate behavior is unaffected.
--   * apply_vehicle_serving_projection's `on conflict (source_table,
--     source_id, canonical_entity_type) do update` upserts are unaffected
--     for the same reason.

drop index if exists canonical_object_map_verified_target_uq;

comment on table canonical_object_map is
  'Operational bridge from legacy TDR UUIDs to stable Vehicle Master IDs. '
  'Matching candidates are never authority until status=verified. '
  'Source-key uniqueness (source_table, source_id, canonical_entity_type) is '
  'enforced; global canonical-target uniqueness is deliberately NOT, so that '
  'multiple external identities may legitimately be verified against the '
  'same canonical entity -- see docs/vehicle-platform/EXTERNAL_IDENTITY_PERSISTENCE.md.';
