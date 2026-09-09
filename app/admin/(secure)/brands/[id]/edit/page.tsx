import { redirect } from "next/navigation";

export default function EditBrand() {
  redirect("/admin?canonical=1");
}
