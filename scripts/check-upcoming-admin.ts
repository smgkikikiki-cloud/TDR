import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseUpcomingCarForm, parseUpcomingUpdate } from "../lib/upcoming-cars-form.ts";

function form(values: Record<string, string>) {
  const result = new FormData();
  for (const [key, value] of Object.entries(values)) result.set(key, value);
  return result;
}

const common = { vehicle_name: "Test car", confidence: "HIGH", launch_year: "2027" };
const rumored = parseUpcomingCarForm(form({ ...common, status: "RUMORED", rumor_half: "H2",
  confirmed_month: "5", confirmed_day: "20", confirmed_quarter: "Q2" }));
assert.equal(rumored.rumor_half, "H2");
assert.equal(rumored.confirmed_month, null);
assert.equal(rumored.confirmed_quarter, null);
assert.equal(rumored.confirmed_day, null);
assert.equal(parseUpcomingCarForm(form({ ...common, status: "CONFIRMED" })).confirmed_quarter, null);
const confirmed = parseUpcomingCarForm(form({ ...common, status: "CONFIRMED", confirmed_month: "5", confirmed_day: "20",
  rumor_half: "H1", internal_notes: "Editor only" }));
assert.equal(confirmed.rumor_half, null);
assert.equal(confirmed.confirmed_month, 5);
assert.equal(confirmed.internal_notes, "Editor only");
for (const values of [
  { ...common, status: "OTHER", rumor_half: "H1" },
  { ...common, status: "RUMORED", rumor_half: "Q1" },
  { ...common, status: "CONFIRMED", confirmed_day: "5" },
  { ...common, status: "CONFIRMED", confirmed_month: "13" },
  { ...common, status: "CONFIRMED", confirmed_month: "7", confirmed_quarter: "Q1" },
  { ...common, status: "CONFIRMED", confidence: "CERTAIN" },
]) assert.throws(() => parseUpcomingCarForm(form(values)));
assert.deepEqual(parseUpcomingUpdate(form({ update_date: "2028-02-29", message: "  Update  " })),
  { update_date: "2028-02-29", message: "Update" });
assert.throws(() => parseUpcomingUpdate(form({ update_date: "2027-02-29", message: "Update" })));
assert.throws(() => parseUpcomingUpdate(form({ update_date: "2027-02-28", message: "  " })));

const actions = readFileSync("app/admin/upcoming-actions.ts", "utf8");
for (const name of ["createUpcomingCar", "updateUpcomingCar", "deleteUpcomingCar", "addUpcomingCarUpdate"]) {
  assert.match(actions, new RegExp(`export async function ${name}\\(form: FormData\\) \\{\\s*const db = await dbForAdmin\\(\\)`));
}
assert.match(actions, /if \(!\(await isAdmin\(\)\)\) redirect\("\/admin\/login"\)/);
assert.match(actions, /\.from\("upcoming_cars"\)\.delete\(\)\.eq\("vehicle_id", id\)/);
assert.match(actions, /upcoming_car_id: car\.id/);
assert.ok(!/canonical|market_trim|model_id|generation_id/i.test(actions));
const formUi = readFileSync("components/admin/UpcomingCarForm.tsx", "utf8");
assert.ok(formUi.includes('name="internal_notes"'));
assert.ok(formUi.includes('name="vehicle_id"'));
assert.ok(formUi.includes("month ?") && formUi.includes('name="confirmed_quarter"'));

console.log("Upcoming admin: form validation, actions and isolation passed");
