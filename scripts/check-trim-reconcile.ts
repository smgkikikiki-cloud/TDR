/**
 * Trim-set / price reconcile (lib/vehicle-engine/trim-reconcile.ts), VEHICLE_DB_V3 §5 and the reconcile cases of §13.
 * Pure: no database, no network, no clock.
 */
import {
  greedyPairs, normalizeTrimName, pairScore, parseAttributes, reconcileModel, tokensOf,
  type Observation, type ReconcileInput, type TrimState,
} from "../lib/vehicle-engine/trim-reconcile.ts";

let failed = 0;
let passed = 0;
function ok(name: string, condition: unknown, detail?: unknown) {
  if (condition) { passed++; return; }
  failed++;
  console.log(`  FAIL ${name}${detail === undefined ? "" : `\n       ${JSON.stringify(detail).slice(0, 500)}`}`);
}

const MODEL = { id: "acme.a", brand_name: "Acme", model_name: "A" };
const TODAY = "2026-10-12";
const trim = (id: string, name: string, price: number | null, extra: Partial<TrimState> = {}): TrimState =>
  ({ trim_id: `acme.a.g1.trim.${id}`, name, status: "CURRENT", price_thb: price, ...extra });
const obs = (name: string, amount: number | null, extra: Partial<Observation> = {}): Observation =>
  ({ name_raw: name, amount_thb: amount, ...extra });
const id = (s: string) => `acme.a.g1.trim.${s}`;

function run(trims: TrimState[], observations: Observation[], extra: Partial<ReconcileInput> = {}) {
  return reconcileModel({
    model: MODEL, trims, observations, extraction_ok: true, prior_amounts: new Map(), today: TODAY,
    model_first_observed_at: "2026-09-01", ...extra,
  });
}
const kinds = (r: ReturnType<typeof run>) => r.proposals.map((p) => p.kind);

const LINEUP = [trim("sv", "SV", 900_000), trim("svplus", "SV+", 1_000_000), trim("top", "Top", 1_100_000)];
const SAME = [obs("SV", 900_000), obs("SV+", 1_000_000), obs("Top", 1_100_000)];

// --- §5.2 normalize -------------------------------------------------------
ok("normalize strips brand/model and year", normalizeTrimName("Acme A 2026 Top", "Acme", "A") === "top");
ok("normalize keeps decimal points", normalizeTrimName("2.4 Top").includes("2.4") && !normalizeTrimName("2.0 Top").startsWith("2top"));
ok("normalize does not eat a 2.0 displacement as a year", normalizeTrimName("2.0 Turbo") === "2.0turbo");
ok("normalize synonym map: hybrid / e:HEV / ไฮบริด -> hev",
  new Set(["Top Hybrid", "Top e:HEV", "Top ไฮบริด", "Top HEV"].map((n) => normalizeTrimName(n))).size === 1);
ok("normalize synonym map: AWD / 4WD / 4x4 -> awd",
  new Set(["Top AWD", "Top 4WD", "Top 4x4", "Top ขับเคลื่อนสี่ล้อ"].map((n) => normalizeTrimName(n))).size === 1);
ok("normalize: spaces and dashes do not matter", normalizeTrimName("Top-Plus") === normalizeTrimName("Top Plus"));
ok("normalize: MY24 and model-year suffix are dropped", normalizeTrimName("Top MY24") === "top" && normalizeTrimName("Top ปี 2026") === "top");
ok("PHEV is not collapsed into HEV", normalizeTrimName("Top PHEV") !== normalizeTrimName("Top HEV"));

// --- §5.4 prices ------------------------------------------------------------
{
  const first = run(LINEUP, [obs("SV", 918_000), ...SAME.slice(1)]);                    // +2 %, first sighting
  ok("+2%: first sighting is pending, nothing applied", first.price_pending.length === 1 && first.price_applies.length === 0, first);
  const second = run(LINEUP, [obs("SV", 918_000), ...SAME.slice(1)], { prior_amounts: new Map([[id("sv"), 918_000]]) });
  ok("+2%: second consecutive sighting applies", second.price_applies.length === 1 && second.price_applies[0].amount_thb === 918_000
    && second.price_applies[0].prior_amount === 900_000 && second.price_jumps.length === 0, second);
  const jump1 = run(LINEUP, [obs("SV", 1_080_000), ...SAME.slice(1)]);
  ok("+20%: first sighting is pending, no card yet", jump1.price_jumps.length === 0 && jump1.price_pending.length === 1, jump1);
  const jump2 = run(LINEUP, [obs("SV", 1_080_000), ...SAME.slice(1)], { prior_amounts: new Map([[id("sv"), 1_080_000]]) });
  ok("+20%: confirmed twice becomes a PRICE_JUMP, never applied",
    jump2.price_jumps.length === 1 && jump2.price_applies.length === 0 && Math.abs(jump2.price_jumps[0].ratio - 0.2) < 1e-9, jump2);
  const edge = run(LINEUP, [obs("SV", 1_035_000), ...SAME.slice(1)], { prior_amounts: new Map([[id("sv"), 1_035_000]]) });
  ok("exactly +15% still applies (the rule is > 15%)", edge.price_applies.length === 1 && edge.price_jumps.length === 0, edge);
  const together = run(LINEUP, [obs("SV", 918_000), obs("SV+", 1_020_000), obs("Top", 1_122_000)], {
    prior_amounts: new Map([[id("sv"), 918_000], [id("svplus"), 1_020_000], [id("top"), 1_122_000]]) });
  ok("all trims up together, no topology change: normal rules, no card",
    together.price_applies.length === 3 && together.proposals.length === 0 && together.status === "OK", together);
  const unchanged = run(LINEUP, SAME);
  ok("same prices: nothing happens", unchanged.price_applies.length + unchanged.price_pending.length + unchanged.proposals.length === 0, unchanged);
  const blank = run(LINEUP, [obs("SV", null), obs("SV+", 0), obs("Top", 1_100_000)]);
  ok("price 0 / blank / contact dealer: no change", blank.price_applies.length + blank.price_pending.length === 0, blank);
  const vat = run(LINEUP, [obs("SV", 918_000, { vat_included: false }), ...SAME.slice(1)], { prior_amounts: new Map([[id("sv"), 918_000]]) });
  ok("price excluding VAT is applied as given with the flag", vat.price_applies[0]?.vat_included === false, vat);
  const first_price = run([trim("sv", "SV", null), ...LINEUP.slice(1)], [obs("SV", 900_000), ...SAME.slice(1)],
    { prior_amounts: new Map([[id("sv"), 900_000]]) });
  ok("a trim with no price yet takes its first confirmed price (no jump rule)", first_price.price_applies.length === 1 && first_price.price_jumps.length === 0, first_price);
  const flipflop = run(LINEUP, [obs("SV", 918_000), ...SAME.slice(1)], { prior_amounts: new Map([[id("sv"), 930_000]]) });
  ok("a different value than last run restarts the count (glitch guard)", flipflop.price_pending.length === 1 && flipflop.price_applies.length === 0, flipflop);
}

// --- §5.1 gates -------------------------------------------------------------
{
  const none = run(LINEUP, []);
  ok("0 observations: batch stopped, no discontinue proposals", none.status === "BATCH_STOPPED" && none.proposals.length === 0, none);
  const failedExtraction = run(LINEUP, SAME, { extraction_ok: false });
  ok("extraction failed: batch stopped", failedExtraction.status === "BATCH_STOPPED" && failedExtraction.price_applies.length === 0);
  const broken = run(LINEUP, [obs("SV", 900_000)]);
  ok("< 50% of CURRENT trims observed: SOURCE_BROKEN, nothing changes",
    broken.status === "SOURCE_BROKEN" && broken.proposals.length === 0 && broken.price_applies.length === 0, broken);
  const half = run(LINEUP, [obs("SV", 900_000), obs("SV+", 1_000_000)]);
  ok("2 of 3 observed is not broken", half.status === "OK", half);
}

// --- §5.1 topology and pairing -----------------------------------------------
{
  const renamed = run(LINEUP, [obs("SV", 900_000), obs("SV Plus", 1_000_000), obs("Top", 1_100_000)]);
  ok("SV+ and 'SV Plus' are different strings but the same trim name? (no: proposes a rename, applies nothing)",
    renamed.matches.length === 2 || renamed.proposals.some((p) => p.kind === "RENAME_TRIM" || p.kind === "ALIAS_TRIM"), renamed);

  const svToSvPlus = run(
    [trim("sv", "SV", 900_000), trim("top", "Top", 1_100_000), trim("x", "X", 1_300_000)],
    [obs("SV+", 905_000), obs("Top", 1_100_000), obs("X", 1_300_000)]);
  const p = svToSvPlus.proposals.find((q) => q.kind === "RENAME_TRIM") as any;
  ok("SV -> SV+ (same slot, near price) pairs as a rename proposal", p && p.trim_id === id("sv") && p.name_raw === "SV+", svToSvPlus);
  ok("a rename never changes the trim's price in the same run", svToSvPlus.price_applies.length === 0 && svToSvPlus.price_pending.length === 0, svToSvPlus);

  const locked = run(
    [trim("sv", "SV", 900_000, { name_locked: true }), trim("top", "Top", 1_100_000), trim("x", "X", 1_300_000)],
    [obs("SV+", 905_000), obs("Top", 1_100_000), obs("X", 1_300_000)]);
  ok("admin-named trim: only an alias proposal, never a rename", locked.proposals.some((q) => q.kind === "ALIAS_TRIM") && !kinds(locked).includes("RENAME_TRIM"), locked);

  const midInsert = run(
    [trim("a", "A Base", 800_000), trim("c", "C Top", 1_200_000), trim("d", "D Max", 1_400_000)],
    [obs("A Base", 800_000), obs("B Mid", 1_000_000), obs("C Top", 1_200_000), obs("D Max", 1_400_000)]);
  ok("trim inserted mid-lineup: one ADD, later trims still matched",
    kinds(midInsert).join() === "ADD_TRIM" && midInsert.matches.length === 3, midInsert);

  const hevPhev = run(
    [trim("a", "Base", 800_000), trim("hev", "2.0 Hybrid", 1_000_000, { last_seen_at: "2026-10-10" }), trim("c", "Top", 1_200_000)],
    [obs("Base", 800_000), obs("2.0 PHEV", 1_005_000), obs("Top", 1_200_000)]);
  ok("HEV is never paired with PHEV (hard reject)", !kinds(hevPhev).some((k) => k === "RENAME_TRIM" || k === "ALIAS_TRIM"), hevPhev);
  ok("...so it is an ADD and the HEV is only 'missing' (no discontinue before 7 days)", kinds(hevPhev).includes("ADD_TRIM") && !kinds(hevPhev).includes("DISCONTINUE_TRIM"), hevPhev);

  const sameAttrs = pairScore({ tokens: tokensOf("2.4 SV 4WD"), price: 1_000_000, slot: 1 }, { tokens: tokensOf("2.8 SV 4WD"), price: 1_000_000, slot: 1 });
  ok("different displacement is a hard reject", sameAttrs === null);
  const drivetrain = pairScore({ tokens: tokensOf("SV 4WD"), price: 1_000_000, slot: 1 }, { tokens: tokensOf("SV 2WD"), price: 1_000_000, slot: 1 });
  ok("different drivetrain is a hard reject", drivetrain === null);
  const seats = pairScore({ tokens: tokensOf("SV 7 ที่นั่ง"), price: 1_000_000, slot: 1 }, { tokens: tokensOf("SV 5 ที่นั่ง"), price: 1_000_000, slot: 1 });
  const seatsSame = pairScore({ tokens: tokensOf("SV 7 ที่นั่ง"), price: 1_000_000, slot: 1 }, { tokens: tokensOf("SV 7 ที่นั่ง"), price: 1_000_000, slot: 1 });
  // tokens {sv, 7seat} vs {sv, 5seat}: Jaccard 1/5 -> 0.4*0.2 + 0.3 (price) + 0.3 (slot) = 0.68, minus the 0.3 seat penalty.
  ok("different seat count costs 0.3", seats !== null && seatsSame === 1 && Math.abs((seats ?? 0) - 0.38) < 1e-9, { seats, seatsSame });
  ok("parseAttributes reads powertrain / displacement / drivetrain / seats",
    JSON.stringify(parseAttributes(tokensOf("2.4 Top PHEV 4WD 7 ที่นั่ง"))) === JSON.stringify({ powertrain: "PHEV", displacement: "2.4", drivetrain: "AWD", seats: "7" }));
  ok("score below the threshold gives no pair", greedyPairs(
    [{ tokens: tokensOf("Alpha"), price: 500_000, slot: 0 }], [{ tokens: tokensOf("Omega"), price: 2_000_000, slot: 3 }], 0.5).length === 0);
  const greedy = greedyPairs(
    [{ tokens: tokensOf("SV"), price: 900_000, slot: 0 }, { tokens: tokensOf("Top"), price: 1_100_000, slot: 1 }],
    [{ tokens: tokensOf("Top+"), price: 1_105_000, slot: 1 }, { tokens: tokensOf("SV+"), price: 905_000, slot: 0 }], 0.5);
  ok("greedy pairing is 1:1 and takes the best score first", greedy.length === 2 && greedy.find((g) => g.left === 0)?.right === 1, greedy);

  const bigChange = run(LINEUP, [obs("Alpha", 700_000), obs("Beta", 800_000), obs("Gamma", 1_700_000), obs("Top", 1_100_000)]);
  ok("lineup change > 50%: one MODEL_REVIEW card, no rename proposals, no price changes",
    bigChange.status === "MODEL_REVIEW" && kinds(bigChange).join() === "MODEL_REVIEW" && bigChange.price_applies.length === 0, bigChange);

  const facelift = run(LINEUP, [...SAME, obs("Facelift Top", 1_150_000)]);
  ok("facelift marker on an unmatched row: one model card, nothing else",
    facelift.status === "MODEL_REVIEW" && kinds(facelift).join() === "MODEL_REVIEW" && facelift.price_applies.length === 0, facelift);
  const thaiMarker = run(LINEUP, SAME, { headline: "โฉมใหม่ Acme A" });
  ok("Thai marker in the headline: one model card", thaiMarker.status === "MODEL_REVIEW", thaiMarker);
  const alreadyNew = run([trim("n", "New Top", 1_100_000), ...LINEUP.slice(0, 2)], [obs("New Top", 1_100_000), ...SAME.slice(0, 2)]);
  ok("a marker that is already part of a matched trim name does not trigger", alreadyNew.status === "OK", alreadyNew);

  const newMy = run(LINEUP, [obs("SV MY2026", 900_000), obs("SV+ 2026", 1_000_000), obs("Top ปี 2026", 1_100_000)]);
  ok("new model year: same trims matched, nothing proposed (existing facts are kept)",
    newMy.status === "OK" && newMy.matches.length === 3 && newMy.proposals.length === 0, newMy);
  const aliased = run([trim("sv", "SV", 900_000, { aliases: ["Standard"] }), ...LINEUP.slice(1)], [obs("Standard", 900_000), ...SAME.slice(1)]);
  ok("a stored alias matches", aliased.matches[0]?.how === "ALIAS" && aliased.proposals.length === 0, aliased);
  const hint = run(LINEUP, [obs("something else", 905_000, { trim_id_hint: id("sv") }), ...SAME.slice(1)]);
  ok("Excel trim_id hint wins over the name", hint.matches[0]?.how === "HINT" && hint.matches[0].trim_id === id("sv"), hint);
}

// --- §5.1 step 8, §6.E ---------------------------------------------------------
{
  const missingYoung = run(
    [...LINEUP, trim("old", "Old", 700_000, { last_seen_at: "2026-10-08" })], SAME);
  ok("missing for 4 days: no discontinue proposal yet", !kinds(missingYoung).includes("DISCONTINUE_TRIM"), missingYoung);
  const missingOld = run(
    [...LINEUP, trim("old", "Old", 700_000, { last_seen_at: "2026-10-05" })], SAME);
  const d = missingOld.proposals.find((q) => q.kind === "DISCONTINUE_TRIM") as any;
  ok("missing 7 days: discontinue is proposed (never applied)", d && d.trim_id === id("old") && d.missing_days === 7, missingOld);
  const neverSeen = run([...LINEUP, trim("ghost", "Ghost", 700_000)], SAME, { model_first_observed_at: "2026-09-01" });
  ok("a trim never seen counts from the model's first successful read", kinds(neverSeen).includes("DISCONTINUE_TRIM"), neverSeen);
  const noHistory = run([...LINEUP, trim("ghost", "Ghost", 700_000)], SAME, { model_first_observed_at: null });
  ok("no history at all: unsure means no proposal", !kinds(noHistory).includes("DISCONTINUE_TRIM"), noHistory);

  const dup = run(LINEUP, [...SAME, obs("sv", 901_000)]);
  ok("the same normalized name twice on the page: ambiguous, no price applied for it, no guess",
    kinds(dup).includes("AMBIGUOUS_NAME") && dup.price_applies.length === 0 && dup.price_pending.length === 0, dup);

  const unverified = run([trim("sv", "SV", 900_000, { status: "UNVERIFIED" }), ...LINEUP.slice(1)], SAME);
  ok("UNVERIFIED trim found on the official page: confirm-as-CURRENT proposal, no price change",
    kinds(unverified).join() === "CONFIRM_CURRENT" && unverified.price_applies.length === 0, unverified);
  const historical = run([trim("sv", "SV", 900_000, { status: "HISTORICAL" }), ...LINEUP.slice(1)], SAME);
  ok("HISTORICAL trim on sale again: reactivate proposal", kinds(historical).join() === "REACTIVATE_TRIM", historical);

  const deterministic = JSON.stringify(run(LINEUP, SAME));
  ok("deterministic: same input, same output", deterministic === JSON.stringify(run(LINEUP, SAME)));
}

console.log(failed ? `\n${failed} FAILED, ${passed} passed` : `all ${passed} trim-reconcile cases passed`);
process.exit(failed ? 1 : 0);
