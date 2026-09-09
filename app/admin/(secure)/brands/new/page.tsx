import { redirect } from "next/navigation";

export default function NewBrand() {
  redirect("/admin?canonical=1");
}
