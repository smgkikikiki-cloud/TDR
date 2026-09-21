"""The exact acceptance case: 1200 OPEN exceptions, paged without loss.

/admin/exceptions used to read `import_run_exceptions` with a bare
`.limit(1000)` and call that the work list. 1200 open rows meant the
last 200 were invisible, with nothing saying so -- the same silent loss
`import_run_exceptions` itself (migration_v41) was built to end, one
layer up. lib/import-exceptions.ts's listOpenExceptionsPage() replaces
that with a keyset page over (created_at, id) plus an exact count; this
proves the query shape it builds -- translated to the raw SQL PostgREST
would run for it -- against a real table of exactly that size.

The registration-gap grouping has the same failure mode in a different
shape: grouping "the first N rows read into memory" can only ever see
the months that happened to land in that slice. import_run_registration_
gaps (the other half of migration_v43) groups server-side over the whole
table instead; proved here with a group whose row count alone exceeds
the old page cap.
"""

from __future__ import annotations

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401

PAGE_SIZE = 200


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    return pg


def _run_id(db, kind: str = "PRICE") -> str:
    return db.scalar(f"""
        insert into public.import_runs (storage_path, original_name, source_kind, status)
        values ('uploads/{kind.lower()}.json', '{kind.lower()}.json', '{kind}', 'COMPLETED')
        returning id""")


def _keyset_page(db, *, cursor: tuple[str, str] | None, page_size: int = PAGE_SIZE,
                 exclude_kind: str | None = None) -> tuple[list[list[str]], bool]:
    """The exact query shape listOpenExceptionsPage() builds through
    PostgREST's `.or(created_at.lt.X,and(created_at.eq.X,id.lt.Y))`,
    written as the SQL it compiles to."""
    where = ["status = 'OPEN'"]
    if exclude_kind:
        where.append(f"kind <> '{exclude_kind}'")
    if cursor:
        created_at, row_id = cursor
        where.append(f"(created_at < '{created_at}' "
                     f"or (created_at = '{created_at}' and id < '{row_id}'))")
    rows = db.rows(f"""
        select id, created_at from public.import_run_exceptions
         where {' and '.join(where)}
         order by created_at desc, id desc
         limit {page_size + 1}
    """)
    has_more = len(rows) > page_size
    return rows[:page_size], has_more


def test_exactly_1200_open_rows_page_without_loss_or_duplication(db):
    run = _run_id(db)
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      select '{run}', 'PRICE', 'PRICE_IDENTITY', 'no trim matched',
             jsonb_build_object('amount_thb', i)
        from generate_series(1, 1200) as i;""")

    total = db.scalar("select count(*) from public.import_run_exceptions where status = 'OPEN'")
    assert total == "1200"

    seen: set[str] = set()
    cursor = None
    pages = 0
    while True:
        rows, has_more = _keyset_page(db, cursor=cursor)
        assert rows, "a page inside the known total must never come back empty"
        pages += 1
        for row_id, _created_at in rows:
            assert row_id not in seen, f"row {row_id} was returned twice across pages"
            seen.add(row_id)
        if not has_more:
            assert len(rows) < PAGE_SIZE + 1
            break
        cursor = (rows[-1][1], rows[-1][0])
        assert pages <= 10, "runaway pagination -- a bug, not slow data"

    assert len(seen) == 1200
    assert pages == 6  # 1200 / 200


def test_page_1_and_page_2_are_visible_and_disjoint(db):
    run = _run_id(db)
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      select '{run}', 'PRICE', 'PRICE_IDENTITY', 'no trim matched',
             jsonb_build_object('amount_thb', i)
        from generate_series(1, 1200) as i;""")

    page1, has_more1 = _keyset_page(db, cursor=None)
    assert len(page1) == PAGE_SIZE
    assert has_more1

    cursor = (page1[-1][1], page1[-1][0])
    page2, has_more2 = _keyset_page(db, cursor=cursor)
    assert len(page2) == PAGE_SIZE
    assert has_more2

    assert {row[0] for row in page1}.isdisjoint({row[0] for row in page2})


def test_resolving_an_item_on_a_later_page_removes_it_from_every_later_read(db):
    run = _run_id(db)
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      select '{run}', 'PRICE', 'PRICE_IDENTITY', 'no trim matched',
             jsonb_build_object('amount_thb', i)
        from generate_series(1, 1200) as i;""")

    page1, _ = _keyset_page(db, cursor=None)
    cursor = (page1[-1][1], page1[-1][0])
    page2, _ = _keyset_page(db, cursor=cursor)
    target_id = page2[len(page2) // 2][0]

    db.sql(f"""update public.import_run_exceptions
               set status = 'RESOLVED', resolved_by = 'owner', resolved_at = now(),
                   resolution_target = 'closed'
             where id = '{target_id}'""")

    assert db.scalar("select count(*) from public.import_run_exceptions"
                     " where status = 'OPEN'") == "1199"
    remaining_ids: set[str] = set()
    cursor = None
    while True:
        rows, has_more = _keyset_page(db, cursor=cursor)
        remaining_ids.update(row[0] for row in rows)
        if not has_more:
            break
        cursor = (rows[-1][1], rows[-1][0])
    assert target_id not in remaining_ids
    assert len(remaining_ids) == 1199


def test_a_registration_kind_row_is_excluded_from_the_general_work_list(db):
    """The general work list pages everything EXCEPT registration gaps,
    which have their own grouped, ungrouped-by-page view."""
    run = _run_id(db, "PRICE")
    reg_run = _run_id(db, "DLT")
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      values ('{run}', 'PRICE', 'PRICE_IDENTITY', 'no trim matched', '{{}}'::jsonb),
             ('{reg_run}', 'DLT', 'REGISTRATION_IDENTITY', 'unknown model',
              '{{"brand": "TOYOTA", "model": "YARIS"}}'::jsonb);""")

    rows, _ = _keyset_page(db, cursor=None, exclude_kind="REGISTRATION_IDENTITY")
    assert len(rows) == 1


# --- the grouped registration-gap view is never capped at a page --------

def test_a_label_with_more_open_months_than_the_old_page_cap_is_still_one_group(db):
    """1200 OPEN rows, all one label -- the old `.limit(1000)` read would
    have missed 200 of them before grouping even started."""
    run = _run_id(db, "DLT")
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      select '{run}', 'DLT', 'REGISTRATION_IDENTITY', 'unknown model',
             jsonb_build_object('registration_type', 'PC', 'brand', 'TOYOTA',
                                'model', 'YARIS', 'period', to_char(
                                  date '2000-01-01' + (i || ' months')::interval, 'YYYY-MM'),
                                'units', 1, 'grain', 'MODEL')
        from generate_series(1, 1200) as i;""")

    row = db.rows("""select months, total_units from public.import_run_registration_gaps
                     where brand_name_raw = 'TOYOTA' and model_name_raw = 'YARIS'""")
    assert row == [["1200", "1200"]]


def test_resolving_the_whole_group_closes_every_row_the_view_named(db):
    run = _run_id(db, "DLT")
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      select '{run}', 'DLT', 'REGISTRATION_IDENTITY', 'unknown model',
             jsonb_build_object('registration_type', 'PC', 'brand', 'TOYOTA',
                                'model', 'YARIS', 'period', to_char(
                                  date '2000-01-01' + (i || ' months')::interval, 'YYYY-MM'),
                                'units', 1, 'grain', 'MODEL')
        from generate_series(1, 1200) as i;""")
    ids_row = db.rows("""select exception_ids from public.import_run_registration_gaps
                         where brand_name_raw = 'TOYOTA' and model_name_raw = 'YARIS'""")
    ids = ids_row[0][0].strip("{}").split(",")
    assert len(ids) == 1200

    db.sql(f"""update public.import_run_exceptions
                  set status = 'RESOLVED', resolved_by = 'owner', resolved_at = now(),
                      resolution_target = 'toyota.yaris'
                where id = any(array{ids!r}::uuid[])""")

    assert db.scalar("select count(*) from public.import_run_registration_gaps"
                     " where brand_name_raw = 'TOYOTA'") == "0"
    assert db.scalar("select count(*) from public.import_run_exceptions"
                     " where status = 'OPEN'") == "0"


def test_a_group_missing_brand_or_model_is_not_produced(db):
    """A degenerate exception (bad source_identity) does not become a
    group nobody can meaningfully act on."""
    run = _run_id(db, "DLT")
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      values ('{run}', 'DLT', 'REGISTRATION_IDENTITY', 'malformed', '{{}}'::jsonb);""")
    assert db.scalar("select count(*) from public.import_run_registration_gaps") == "0"
