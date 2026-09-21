"""Bulk import writes trim columns, and only where it is entitled to."""

from vehreg.source_import import (
    CREATED, EXCEPTION, PATCHED, UNCHANGED,
    ExistingTrim, SourceRow, batches_from_commands, commands_from_outcomes,
    resolve_rows, summarize,
)

GEN = "toyota.camry.axvh70"
MODEL = "toyota.camry"


def trim(name="Premium", canonical_id=f"{GEN}.trim.premium", **columns):
    source_ids = columns.pop("source_ids", ())
    return ExistingTrim(canonical_id=canonical_id, model_id=MODEL, generation_id=GEN,
                        name=name, powertrain="HEV", columns=columns, source_ids=source_ids)


def row(source_id="eco-1", name="Premium", kind="ECO", **values):
    return SourceRow(source_id=source_id, source_kind=kind, model_id=MODEL,
                     generation_id=GEN, powertrain="HEV", trim_name=name, values=values)


def only(outcomes):
    assert len(outcomes) == 1
    return outcomes[0]


# ---------------------------------------------------------------------------
# What a source may write
# ---------------------------------------------------------------------------

def test_a_field_the_source_leaves_blank_is_not_touched():
    out = only(resolve_rows([row(**{"vehicle.seats": None})], [trim(seats=5)]))
    assert "seats" not in out.patch


def test_a_value_lands_where_nothing_is_held():
    out = only(resolve_rows([row(**{"vehicle.seats": 7})], [trim()]))
    assert out.status == PATCHED and out.patch["seats"] == 7


def test_an_identical_value_writes_nothing():
    out = only(resolve_rows([row(source_id="eco-1", **{"vehicle.seats": 5})],
                            [trim(seats=5, source_ids=("eco-1",))]))
    assert out.status == UNCHANGED and out.patch == {}


def test_a_homologation_measurement_overrules_what_was_held():
    """ECO Sticker is a filed measurement; a stale hand-typed length loses."""
    out = only(resolve_rows([row(**{"vehicle.length_mm": 4885})], [trim(length_mm=4880)]))
    assert out.status == PATCHED and out.patch["length_mm"] == 4885


def test_a_source_not_authoritative_for_a_field_reports_instead_of_overwriting():
    out = only(resolve_rows([row(kind="MEDIA", **{"vehicle.seats": 4})], [trim(seats=5)]))
    assert out.patch == {}
    assert out.conflicts == [{"column": "seats", "held": 5, "incoming": 4}]


def test_a_field_with_no_trim_column_is_dropped_rather_than_written_elsewhere():
    """CO2 has no column on the trim, and SpecLedger is not served."""
    out = only(resolve_rows([row(**{"emissions.co2_g_km": 120})], [trim(source_ids=("eco-1",))]))
    assert out.patch == {} and out.status == UNCHANGED


# ---------------------------------------------------------------------------
# Which car a row is
# ---------------------------------------------------------------------------

def test_a_source_id_already_recorded_resolves_to_that_trim():
    """A re-approval is the same car filed twice, not a second car."""
    out = only(resolve_rows([row(source_id="eco-9", name="totally different wording")],
                            [trim(source_ids=("eco-9",))]))
    assert out.trim_id == f"{GEN}.trim.premium"
    assert out.status in (PATCHED, UNCHANGED)


def test_an_exact_name_match_inside_one_generation_resolves():
    out = only(resolve_rows([row(name="premium")], [trim(name="Premium")]))
    assert out.trim_id == f"{GEN}.trim.premium"


def test_two_trims_with_the_same_exact_name_are_an_exception_not_a_guess():
    out = only(resolve_rows([row()], [trim(), trim(canonical_id=f"{GEN}.trim.premium_2")]))
    assert out.status == EXCEPTION and "share this exact name" in out.reason


def test_a_grade_is_created_only_where_nothing_could_be_a_second_copy_of_it():
    """No trim of this model sells this powertrain yet, so there is nothing
    the new name could be a re-wording of."""
    out = only(resolve_rows([row(name="Premium Luxury", **{"vehicle.seats": 5})],
                            [], known_generations=[GEN]))
    assert out.status == CREATED and out.patch["seats"] == 5


def test_an_unmatched_name_beside_existing_grades_is_an_exception_not_a_new_car():
    """"2.0 RF 6MT" may be a new grade or may be the catalogue's "2.0 RF 6MT
    (Retractable Fastback Manual)" worded differently. The source does not
    say which, so the catalogue does not grow a second copy on a guess."""
    out = only(resolve_rows([row(name="Grand Touring Plus")],
                            [trim(name="Premium")], known_generations=[GEN]))
    assert out.status == EXCEPTION
    assert "went unmatched" in out.reason and "Premium" in out.reason


def test_a_leftover_row_is_new_once_every_existing_grade_is_spoken_for():
    """The run matches "Premium" to the catalogue's only grade, so the
    second row cannot be that grade re-worded -- there is nothing left for
    it to be a copy of, and it becomes the new car it plainly is."""
    outcomes = resolve_rows(
        [row(source_id="a", name="Premium"), row(source_id="b", name="Grand Touring")],
        [trim(name="Premium")], known_generations=[GEN])
    assert [o.status for o in outcomes] == [PATCHED, CREATED]


# ---------------------------------------------------------------------------
# The same car, written the way each source writes it
# ---------------------------------------------------------------------------

def test_word_order_does_not_make_it_a_different_car():
    out = only(resolve_rows([row(name="e:HEV SPADA PREMIUM LINE")],
                            [trim(name="Spada Premium Line e:HEV")]))
    assert out.trim_id == f"{GEN}.trim.premium"


def test_a_parenthetical_note_in_a_catalogue_name_is_not_part_of_the_grade():
    out = only(resolve_rows([row(name="2.0 RF 6MT")],
                            [trim(name="2.0 RF 6MT (Retractable Fastback Manual)")]))
    assert out.trim_id == f"{GEN}.trim.premium"


def test_the_exports_own_boilerplate_is_not_part_of_the_grade():
    out = only(resolve_rows([row(name="HYBRID G CAR")], [trim(name="HYBRID G")]))
    assert out.trim_id == f"{GEN}.trim.premium"


def test_two_genuinely_different_grades_still_do_not_match():
    out = only(resolve_rows([row(name="HYBRID Z 2WD")],
                            [trim(name="HYBRID G 2WD")], known_generations=[GEN]))
    assert out.status == EXCEPTION


def test_a_grade_under_an_unknown_generation_is_an_exception():
    out = only(resolve_rows([row(name="Mystery")], [trim()], known_generations=[]))
    assert out.status == EXCEPTION and "not in the catalogue" in out.reason


def test_a_row_with_no_grade_name_is_an_exception():
    out = only(resolve_rows([row(name="  ")], [trim()], known_generations=[GEN]))
    assert out.status == EXCEPTION


# ---------------------------------------------------------------------------
# What gets compiled
# ---------------------------------------------------------------------------

def test_a_patch_compiles_to_one_bundle_that_keeps_the_existing_identity():
    existing = trim(seats=5)
    outcomes = resolve_rows([row(**{"vehicle.length_mm": 4885})], [existing])
    commands, stranded = commands_from_outcomes(
        outcomes, generation_codes={GEN: "AXVH70"},
        existing_by_trim={existing.canonical_id: existing})
    assert not stranded and len(commands) == 1
    payload = commands[0]["payload"]
    assert payload["generation"] == {"code": "AXVH70"}
    written = payload["trims"][0]
    assert written["canonical_id"] == existing.canonical_id
    assert written["length_mm"] == 4885
    # Untouched columns are absent, so the stored value survives the merge.
    assert "seats" not in written
    assert written["source_refs"]["eco"] == ["eco-1"]


def test_a_repeat_import_of_the_same_record_compiles_to_nothing():
    existing = trim(seats=5, length_mm=4885, source_ids=("eco-1",))
    outcomes = resolve_rows(
        [row(**{"vehicle.seats": 5, "vehicle.length_mm": 4885})], [existing])
    commands, _ = commands_from_outcomes(
        outcomes, generation_codes={GEN: "AXVH70"},
        existing_by_trim={existing.canonical_id: existing})
    assert outcomes[0].status == UNCHANGED and commands == []


def test_batches_stay_within_the_command_ceiling():
    commands = [{"operation": "UPSERT_MODEL_BUNDLE"}] * 900
    batches = batches_from_commands(commands, year=2026, source_kind="ECO",
                                    source_ref="ref", batch_prefix="eco")
    assert [len(b["commands"]) for b in batches] == [400, 400, 100]
    assert {b["source"]["kind"] for b in batches} == {"ECO"}


def test_the_summary_counts_every_row():
    outcomes = resolve_rows(
        [row(source_id="a", **{"vehicle.seats": 7}),
         row(source_id="b", name="Brand New", **{"vehicle.seats": 5})],
        [trim()], known_generations=[GEN])
    counts = summarize(outcomes)
    assert counts[PATCHED] == 1 and counts[CREATED] == 1
    assert sum(counts.values()) == 2
