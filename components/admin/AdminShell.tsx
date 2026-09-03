import { ReactNode } from "react";
import { AdminNav } from "@/components/admin/AdminNav";

export function AdminShell({ children }: { children: ReactNode }) {
  return <div className="adminShell"><AdminNav/><div className="adminMain">{children}</div></div>;
}
