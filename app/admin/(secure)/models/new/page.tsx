import { redirect } from "next/navigation";

/** New vehicles are created once in automotive/vehicle_master. */
export default function NewModel() {
  redirect("/admin?canonical=1");
}
