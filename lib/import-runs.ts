import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

/** Where tools/import_source.py leaves what it did. Read straight from the
 *  repo, the same way the catalogue itself is read -- an import run is a
 *  fact about the data, so it lives with the data rather than in a table. */
const ROOT = path.join(process.cwd(), "automotive/vehicle_master/vehreg/data");

export type ImportReport = {
  stem: string;
  rows_read: number;
  rows_placed: number;
  patched: number;
  created: number;
  unchanged: number;
  exceptions: number;
  conflicts: number;
  commands: number;
  applied: boolean;
};

export type ImportException = {
  source_id?: string;
  model_id?: string;
  brand?: string;
  model?: string;
  trim_name?: string;
  powertrain?: string;
  reason: string;
};

function trimsDir(year: number) {
  return path.join(ROOT, String(year), "market", "trims");
}

function readJson<T>(file: string): T | null {
  try {
    return JSON.parse(readFileSync(file, "utf8")) as T;
  } catch {
    return null;
  }
}

export function importReports(year: number): ImportReport[] {
  let names: string[] = [];
  try {
    names = readdirSync(trimsDir(year));
  } catch {
    return [];
  }
  return names
    .filter((name) => name.startsWith("import_") && name.endsWith("_report.json"))
    .map((name) => {
      const report = readJson<ImportReport>(path.join(trimsDir(year), name));
      return report ? { ...report, stem: name.replace(/_report\.json$/, "") } : null;
    })
    .filter((row): row is ImportReport => row !== null);
}

export function importExceptions(year: number): { stem: string; rows: ImportException[] }[] {
  return importReports(year).map((report) => ({
    stem: report.stem,
    rows: readJson<{ exceptions: ImportException[] }>(
      path.join(trimsDir(year), `${report.stem}_exceptions.json`))?.exceptions ?? [],
  }));
}
