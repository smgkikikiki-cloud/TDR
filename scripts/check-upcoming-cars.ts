import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  confirmedQuarterForDisplay, displayUpcomingTiming, isUpcomingTiming, type UpcomingTiming,
} from "../lib/upcoming-cars-domain.ts";

const sql = readFileSync("supabase/migration_v52_upcoming_cars.sql", "utf8");
const access = readFileSync("lib/upcoming-cars.ts", "utf8");
const base: UpcomingTiming = {
  status: "RUMORED", confidence: "MEDIUM", launchYear: 2027,
  rumorHalf: "H1", confirmedQuarter: null, confirmedMonth: null, confirmedDay: null,
};

for (const status of ["RUMORED", "CONFIRMED"]) {
  assert.match(sql, new RegExp(`status in \\([^)]*'${status}'`));
}
for (const confidence of ["HIGH", "MEDIUM", "LOW"]) {
  assert.ok(isUpcomingTiming({ ...base, confidence: confidence as UpcomingTiming["confidence"] }));
  assert.match(sql, new RegExp(`confidence in \\([^)]*'${confidence}'`));
}
assert.ok(!isUpcomingTiming({ ...base, status: "PLANNED" as UpcomingTiming["status"] }));
assert.ok(!isUpcomingTiming({ ...base, confidence: "CERTAIN" as UpcomingTiming["confidence"] }));

assert.equal(displayUpcomingTiming(base), "H1 2027");
assert.equal(displayUpcomingTiming({ ...base, rumorHalf: "H2" }), "H2 2027");
assert.ok(!isUpcomingTiming({ ...base, rumorHalf: "Q1" as UpcomingTiming["rumorHalf"] }));
assert.match(sql, /rumor_half text check \(rumor_half in \('H1', 'H2'\)\)/);

const confirmed: UpcomingTiming = { ...base, status: "CONFIRMED", rumorHalf: null };
assert.equal(displayUpcomingTiming(confirmed), "2027");
assert.equal(displayUpcomingTiming({ ...confirmed, confirmedQuarter: "Q2" }), "Q2 2027");
assert.equal(displayUpcomingTiming({ ...confirmed, confirmedMonth: 5 }), "05/2027");
assert.equal(confirmedQuarterForDisplay({ ...confirmed, confirmedMonth: 5 }), "Q2");
assert.equal(displayUpcomingTiming({ ...confirmed, confirmedMonth: 5, confirmedDay: 14 }), "14/05/2027");
assert.ok(!isUpcomingTiming({ ...confirmed, confirmedDay: 14 }));
assert.ok(!isUpcomingTiming({ ...confirmed, confirmedMonth: 5, confirmedQuarter: "Q3" }));
assert.ok(!isUpcomingTiming({ ...base, confirmedMonth: 5 }));
assert.match(sql, /confirmed_day is null or confirmed_month is not null/);
assert.match(sql, /confirmed_month is null or confirmed_quarter is null/);

assert.match(sql, /upcoming_car_id bigint not null references public\.upcoming_cars\(id\) on delete cascade/);
assert.match(access, /\.eq\("upcoming_car_id", row\.id\)/);
assert.ok(!/canonical|market_trim|model_id|generation_id/i.test(sql.replace(/^--.*$/gm, "")));
assert.ok(!/canonical|market_trim|model_id|generation_id/i.test(access));
assert.ok(!/const CAR_COLUMNS = [^\n]*internal_notes/.test(access));

console.log("Upcoming Cars: statuses, confidence, timing, update association and isolation passed");
