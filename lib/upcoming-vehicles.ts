import rawUpcoming from "@/data/upcoming/vehicles.json";
import {
  launchYear,
  validateUpcomingDataset,
  type UpcomingDataset,
  type UpcomingVehicle,
} from "@/lib/upcoming-schema";

const problems = validateUpcomingDataset(rawUpcoming);
if (problems.length) {
  throw new Error(`Invalid upcoming vehicle dataset: ${problems.join("; ")}`);
}

const dataset = rawUpcoming as UpcomingDataset;

export function getUpcomingVehicles() {
  return [...dataset.vehicles] as UpcomingVehicle[];
}

export function getPublicUpcomingVehicles() {
  return getUpcomingVehicles().filter((vehicle) => vehicle.visibility === "PUBLIC");
}

export function getPublicUpcomingVehicleBySlug(slug: string) {
  return getPublicUpcomingVehicles().find((vehicle) => vehicle.slug === slug) || null;
}

export function upcomingYears(vehicles: UpcomingVehicle[]) {
  return [...new Set(vehicles.map(launchYear).filter((value): value is number => value !== null))].sort((a, b) => a - b);
}

export function upcomingBrands(vehicles: UpcomingVehicle[]) {
  return [...new Set(vehicles.map((vehicle) => vehicle.brand).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

export function upcomingPowertrains(vehicles: UpcomingVehicle[]) {
  return [...new Set(vehicles.flatMap((vehicle) => vehicle.powertrains || []).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

export function upcomingBodyTypes(vehicles: UpcomingVehicle[]) {
  return [...new Set(vehicles.map((vehicle) => vehicle.body_type).filter((value): value is string => Boolean(value)))].sort((a, b) => a.localeCompare(b));
}
