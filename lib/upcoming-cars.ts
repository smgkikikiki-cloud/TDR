/** Server-side editorial reads. Admin-only notes are never selected here. */
import { adminDb } from "@/lib/supabase";
import type { UpcomingConfidence, UpcomingStatus, RumorHalf, ConfirmedQuarter } from "@/lib/upcoming-cars-domain";

export type UpcomingCar = {
  id: number;
  vehicleId: string;
  vehicleName: string;
  status: UpcomingStatus;
  confidence: UpcomingConfidence;
  launchYear: number;
  rumorHalf: RumorHalf | null;
  confirmedQuarter: ConfirmedQuarter | null;
  confirmedMonth: number | null;
  confirmedDay: number | null;
  description: string;
  createdAt: string;
  updatedAt: string;
};

export type UpcomingCarUpdate = {
  id: number;
  upcomingCarId: number;
  updateDate: string;
  message: string;
  createdAt: string;
};

const CAR_COLUMNS = "id,vehicle_id,vehicle_name,status,confidence,launch_year,rumor_half,confirmed_quarter,confirmed_month,confirmed_day,description,created_at,updated_at";

function carFromRow(row: any): UpcomingCar {
  return {
    id: row.id, vehicleId: row.vehicle_id, vehicleName: row.vehicle_name,
    status: row.status, confidence: row.confidence, launchYear: row.launch_year,
    rumorHalf: row.rumor_half, confirmedQuarter: row.confirmed_quarter,
    confirmedMonth: row.confirmed_month, confirmedDay: row.confirmed_day,
    description: row.description, createdAt: row.created_at, updatedAt: row.updated_at,
  };
}

export async function listUpcomingCars(): Promise<UpcomingCar[]> {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db.from("upcoming_cars").select(CAR_COLUMNS)
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data || []).map(carFromRow);
}

export async function getUpcomingCar(vehicleId: string): Promise<
  { car: UpcomingCar; updates: UpcomingCarUpdate[] } | null
> {
  const db = adminDb();
  if (!db) return null;
  const { data: row, error } = await db.from("upcoming_cars").select(CAR_COLUMNS)
    .eq("vehicle_id", vehicleId).maybeSingle();
  if (error) throw error;
  if (!row) return null;
  const { data: updates, error: updatesError } = await db.from("upcoming_car_updates")
    .select("id,upcoming_car_id,update_date,message,created_at")
    .eq("upcoming_car_id", row.id)
    .order("update_date", { ascending: false }).order("id", { ascending: false });
  if (updatesError) throw updatesError;
  return {
    car: carFromRow(row),
    updates: (updates || []).map((update) => ({
      id: update.id, upcomingCarId: update.upcoming_car_id,
      updateDate: update.update_date, message: update.message, createdAt: update.created_at,
    })),
  };
}
