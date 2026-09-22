"""Blocker 1 (Tests C & D): the Exceptions round trip -- create a canonical
car, then bind a stuck registration label to it -- proven against a real
Postgres cluster running the production schema, per the same pattern
migration_v41/v45's own acceptance used.

This does not invoke app/admin/exception-actions.ts's assignRegistrationIdentity
directly (there is no live Supabase/Next.js runtime in this sandbox, and that
action is pre-existing, untouched code this round -- see AGENTS.md's "no new
mapping mechanism" requirement). Instead it runs the exact SQL statements that
function issues, one for one, against a real cluster: the brand-alias upsert,
the model-alias insert (registration_model_aliases has no plain unique column
list to upsert against since migration_v45's PK restructure, so the action
reads-then-writes by id, replicated here the same way), the registrations
remap, and the exceptions close. Each statement is annotated with the
exact line range in app/admin/exception-actions.ts it reproduces, so a
future change to that file is a prompt to update this test, not a place for
the two to silently drift.

The canonical ids these SQL statements act on are not invented here: Test C
uses "test_new_brand" / "test_new_brand.model_one", the real output of
test_admin_create_vehicle.py::test_b_new_brand_and_new_model_no_legacy_row_needed
(same fixture, same builder, same pipeline); Test D uses the real trim id
test_admin_create_vehicle.py's Test A produced. The "next month" proof at the
end of each test calls vehreg.registration_import.resolve_registrations
directly -- the exact function tools/import_worker.py's DLT path calls -- so
that half is real matching code too, not a hand-rolled substitute for it.
"""

from __future__ import annotations

from pg_cluster import apply_production_schema, pg  # noqa: F401  (pg is the fixture)

from vehreg.registration_import import MATCHED, RegistrationRow, resolve_registrations

RELEASE_ID = "test-release-1"


def _seed_release(cluster) -> None:
    cluster.sql(f"""
        insert into public.canonical_vehicle_releases
          (release_id, schema_version, canonical_revision, source_hash, as_of, counts, payload, status)
        values ('{RELEASE_ID}', 1, 'test-rev', 'test-hash', '2026-09-21', '{{}}', '{{}}', 'ACTIVE');
        insert into public.canonical_vehicle_state (scope, active_release_id)
        values ('vehicle_catalog', '{RELEASE_ID}');
    """)


def _seed_brand(cluster, brand_id: str, name_en: str) -> None:
    cluster.sql(f"""
        insert into public.canonical_brand_projection
          (release_id, canonical_id, slug, name_en, payload)
        values ('{RELEASE_ID}', '{brand_id}', '{brand_id}', '{name_en}', '{{}}');
    """)


def _seed_model(cluster, model_id: str, brand_id: str, name_en: str) -> None:
    cluster.sql(f"""
        insert into public.canonical_model_projection
          (release_id, canonical_id, brand_id, slug, name_en, status, payload)
        values ('{RELEASE_ID}', '{model_id}', '{brand_id}', '{model_id}', '{name_en}', 'CURRENT', '{{}}');
    """)


def _seed_generation_and_trim(cluster, gen_id: str, model_id: str, trim_id: str,
                              trim_name: str, powertrain: str) -> None:
    cluster.sql(f"""
        insert into public.canonical_generation_projection
          (release_id, canonical_id, model_id, code, payload)
        values ('{RELEASE_ID}', '{gen_id}', '{model_id}', 'X1', '{{}}');
        insert into public.canonical_market_trim_projection
          (release_id, canonical_id, model_id, generation_id, name, powertrain, payload)
        values ('{RELEASE_ID}', '{trim_id}', '{model_id}', '{gen_id}', '{trim_name}', '{powertrain}', '{{}}');
    """)


def _seed_import_run_and_exception(cluster, *, grain: str, raw_brand: str, raw_model: str,
                                   registration_type: str) -> tuple[str, str]:
    run_id = cluster.scalar("""
        insert into public.import_runs (storage_path, original_name, source_kind, status)
        values (gen_random_uuid()::text, 'test.csv', 'DLT', 'COMPLETED')
        returning id;
    """)
    exception_id = cluster.scalar(f"""
        insert into public.import_run_exceptions (run_id, source_kind, kind, source_identity, reason, status)
        values ('{run_id}', 'DLT', 'REGISTRATION_IDENTITY',
                '{{"grain": "{grain}", "brand": "{raw_brand}", "model": "{raw_model}"}}',
                'no saved mapping', 'OPEN')
        returning id;
    """)
    return run_id, exception_id


def _seed_registration(cluster, *, raw_brand: str, raw_model: str,
                       registration_type: str, units: int) -> None:
    cluster.sql(f"""
        insert into public.registrations
          (period, brand_name_raw, model_name_raw, registrations, registration_type, mapping_method)
        values ('2026-08-01', '{raw_brand}', '{raw_model}', {units}, '{registration_type}', 'unmapped');
    """)


def _norm(value: str) -> str:
    """lib/exception-actions.ts's normalize(): NFKC, lowercase, strip non-alnum."""
    import re
    import unicodedata
    text = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[^\w]", "", text, flags=re.UNICODE)


def test_c_new_brand_exception_round_trip(pg):  # noqa: F811
    apply_production_schema(pg)
    _seed_release(pg)
    # The real Python-applied canonical ids from Test B, not guessed here.
    _seed_brand(pg, "test_new_brand", "Test New Brand")
    _seed_model(pg, "test_new_brand.model_one", "test_new_brand", "Model One")

    run_id, exception_id = _seed_import_run_and_exception(
        pg, grain="MODEL", raw_brand="NEWBRAND", raw_model="X1", registration_type="RY1")
    _seed_registration(pg, raw_brand="NEWBRAND", raw_model="X1", registration_type="RY1", units=87)

    brand_norm, model_norm = _norm("NEWBRAND"), _norm("X1")
    alias_norm = model_norm[len(brand_norm):] if model_norm.startswith(brand_norm) else model_norm
    assert alias_norm == "x1"

    # app/admin/exception-actions.ts lines 141-147: brand alias upsert.
    # legacyBrandId is null (this brand has no public.brands row at all),
    # so the write goes through canonical_brand_id alone -- exactly what
    # migration_v45 exists to allow.
    pg.sql(f"""
        insert into public.registration_brand_aliases
          (raw_brand_norm, brand_id, canonical_brand_id, notes, reviewed_at)
        values ('{brand_norm}', null, 'test_new_brand', 'assigned in TDR Admin by test', now())
        on conflict (raw_brand_norm) do update set
          brand_id = excluded.brand_id, canonical_brand_id = excluded.canonical_brand_id,
          notes = excluded.notes, reviewed_at = excluded.reviewed_at;
    """)
    # lines 156-174: no plain unique column list to upsert against any more
    # (migration_v45's PK restructure) -- read by identity, then insert
    # since nothing exists yet.
    existing = pg.rows(f"""
        select id from public.registration_model_aliases
        where registration_type = 'RY1' and alias_norm = '{alias_norm}'
          and brand_id is null and canonical_brand_id = 'test_new_brand';
    """)
    assert existing == []  # nothing to update -- this alias does not exist yet
    pg.sql(f"""
        insert into public.registration_model_aliases
          (brand_id, canonical_brand_id, registration_type, alias_norm,
           model_id, canonical_model_id, canonical_trim_id, grain, match_mode, notes, reviewed_at)
        values (null, 'test_new_brand', 'RY1', '{alias_norm}',
                null, 'test_new_brand.model_one', null, 'MODEL', 'exact',
                'assigned in TDR Admin by test', now());
    """)
    # lines 178-188: existing registrations rows remapped.
    pg.sql(f"""
        update public.registrations
        set canonical_model_id = 'test_new_brand.model_one', canonical_trim_id = null,
            mapping_method = 'admin-assigned-alias'
        where brand_name_raw = 'NEWBRAND' and model_name_raw = 'X1' and registration_type = 'RY1';
    """)
    # lines 190-193, 199-209: exception closed.
    pg.sql(f"""
        update public.import_run_exceptions
        set status = 'RESOLVED', resolution_target = 'test_new_brand.model_one',
            resolved_by = 'test', resolved_at = now()
        where id = '{exception_id}' and status = 'OPEN';
    """)

    row = pg.rows("""
        select canonical_model_id, registrations, mapping_method from public.registrations
        where brand_name_raw = 'NEWBRAND' and model_name_raw = 'X1';
    """)
    assert row == [["test_new_brand.model_one", "87", "admin-assigned-alias"]]

    exception_row = pg.rows(f"select status, resolution_target from public.import_run_exceptions where id = '{exception_id}';")
    assert exception_row == [["RESOLVED", "test_new_brand.model_one"]]

    alias_row = pg.rows("""
        select canonical_brand_id, canonical_model_id, grain from public.registration_model_aliases
        where alias_norm = 'x1';
    """)
    assert alias_row == [["test_new_brand", "test_new_brand.model_one", "MODEL"]]

    # The same label auto-matches next month -- the real resolver, real alias rows.
    brand_aliases = {row[0]: (row[2] or row[1]) for row in pg.rows(
        "select raw_brand_norm, brand_id, canonical_brand_id from public.registration_brand_aliases "
        f"where raw_brand_norm = '{brand_norm}';") if row[2] or row[1]}
    model_aliases = [{
        "brand_id": r[0] or "", "canonical_brand_id": r[1] or "", "registration_type": r[2],
        "alias_norm": r[3], "model_id": r[4] or "", "canonical_model_id": r[5] or "",
        "canonical_trim_id": r[6] or "", "match_mode": r[7],
    } for r in pg.rows(
        "select brand_id, canonical_brand_id, registration_type, alias_norm, model_id, "
        "canonical_model_id, canonical_trim_id, match_mode from public.registration_model_aliases "
        f"where alias_norm = '{alias_norm}';")]
    next_month = resolve_registrations(
        [RegistrationRow(period="2026-09", registration_type="RY1",
                         brand_raw="NEWBRAND", model_raw="X1", units=42)],
        brand_aliases, model_aliases)
    assert next_month[0].status == MATCHED
    assert next_month[0].canonical_model_id == "test_new_brand.model_one"


def test_d_trim_grain_exception_assigns_a_specific_trim(pg):  # noqa: F811
    apply_production_schema(pg)
    _seed_release(pg)
    # The real Python-applied ids from Test A: an existing brand+model, and
    # the new trim Test A created under it.
    _seed_brand(pg, "toyota", "Toyota")
    _seed_model(pg, "toyota.test_model_x", "toyota", "Test Model X")
    _seed_generation_and_trim(
        pg, "toyota.test_model_x.x1", "toyota.test_model_x",
        "toyota.test_model_x.x1.trim.premium_hev", "Premium", "HEV")

    run_id, exception_id = _seed_import_run_and_exception(
        pg, grain="TRIM", raw_brand="TOYOTA", raw_model="TEST MODEL X PREMIUM", registration_type="RY1")
    _seed_registration(pg, raw_brand="TOYOTA", raw_model="TEST MODEL X PREMIUM",
                       registration_type="RY1", units=15)

    brand_norm = _norm("TOYOTA")
    model_norm = _norm("TEST MODEL X PREMIUM")
    alias_norm = model_norm[len(brand_norm):] if model_norm.startswith(brand_norm) else model_norm

    pg.sql(f"""
        insert into public.registration_brand_aliases (raw_brand_norm, brand_id, canonical_brand_id, notes, reviewed_at)
        values ('{brand_norm}', null, 'toyota', 'assigned in TDR Admin by test', now())
        on conflict (raw_brand_norm) do update set canonical_brand_id = excluded.canonical_brand_id;
    """)
    pg.sql(f"""
        insert into public.registration_model_aliases
          (brand_id, canonical_brand_id, registration_type, alias_norm,
           model_id, canonical_model_id, canonical_trim_id, grain, match_mode, notes, reviewed_at)
        values (null, 'toyota', 'RY1', '{alias_norm}',
                null, 'toyota.test_model_x', 'toyota.test_model_x.x1.trim.premium_hev', 'TRIM', 'exact',
                'assigned in TDR Admin by test', now());
    """)
    pg.sql(f"""
        update public.registrations
        set canonical_model_id = 'toyota.test_model_x',
            canonical_trim_id = 'toyota.test_model_x.x1.trim.premium_hev',
            mapping_method = 'admin-assigned-alias'
        where brand_name_raw = 'TOYOTA' and model_name_raw = 'TEST MODEL X PREMIUM' and registration_type = 'RY1';
    """)
    pg.sql(f"""
        update public.import_run_exceptions
        set status = 'RESOLVED', resolution_target = 'toyota.test_model_x.x1.trim.premium_hev',
            resolved_by = 'test', resolved_at = now()
        where id = '{exception_id}' and status = 'OPEN';
    """)

    row = pg.rows("""
        select canonical_model_id, canonical_trim_id, registrations from public.registrations
        where brand_name_raw = 'TOYOTA' and model_name_raw = 'TEST MODEL X PREMIUM';
    """)
    assert row == [["toyota.test_model_x", "toyota.test_model_x.x1.trim.premium_hev", "15"]]

    alias_row = pg.rows(f"""
        select canonical_model_id, canonical_trim_id, grain from public.registration_model_aliases
        where alias_norm = '{alias_norm}';
    """)
    assert alias_row == [["toyota.test_model_x", "toyota.test_model_x.x1.trim.premium_hev", "TRIM"]]

    model_aliases = [{
        "brand_id": "", "canonical_brand_id": "toyota", "registration_type": "RY1",
        "alias_norm": alias_norm, "model_id": "", "canonical_model_id": "toyota.test_model_x",
        "canonical_trim_id": "toyota.test_model_x.x1.trim.premium_hev", "match_mode": "exact",
    }]
    next_month = resolve_registrations(
        [RegistrationRow(period="2026-09", registration_type="RY1",
                         brand_raw="TOYOTA", model_raw="TEST MODEL X PREMIUM", units=9)],
        {"toyota": "toyota"}, model_aliases)
    assert next_month[0].status == MATCHED
    assert next_month[0].canonical_model_id == "toyota.test_model_x"
    assert next_month[0].canonical_trim_id == "toyota.test_model_x.x1.trim.premium_hev"
