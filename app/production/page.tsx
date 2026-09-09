import { redirect } from "next/navigation";

/** Industry context now appears on each canonical model page. */
export default function ProductionIndex() {
  redirect("/models");
}
