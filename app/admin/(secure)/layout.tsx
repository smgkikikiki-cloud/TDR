import { ReactNode } from "react";
import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";
import { AdminShell } from "@/components/admin/AdminShell";
export default async function SecureAdminLayout({children}:{children:ReactNode}){if(!(await isAdmin()))redirect('/admin/login');return <AdminShell>{children}</AdminShell>}
