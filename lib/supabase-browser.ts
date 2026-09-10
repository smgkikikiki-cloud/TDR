"use client";

import { createClient, SupabaseClient } from "@supabase/supabase-js";

const TDR_SUPABASE_URL = "https://ltvwzkffmpudpjfjomrg.supabase.co";
const TDR_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_bFWJkCQOyVU07PYMebjLgQ_yfb6bgQX";

let client: SupabaseClient | null | undefined;

export function browserDb(): SupabaseClient | null {
  if (client !== undefined) return client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || TDR_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || TDR_SUPABASE_PUBLISHABLE_KEY;
  client = url && key ? createClient(url, key) : null;
  return client;
}
