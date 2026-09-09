import { redirect } from "next/navigation";

/** New vehicles are created once in automotive/Vehicle Master. */
export default function NewModel() {
  redirect("/admin?canonical=1");
}
