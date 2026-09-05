import { redirect } from "next/navigation";

/** The plant index merged into /production; plant detail pages stay where
 *  they are. Kept as a redirect so existing links do not break. */
export default function PlantsIndex() {
  redirect("/production");
}
