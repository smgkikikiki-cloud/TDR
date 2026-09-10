import { createClient, SupabaseClient } from "@supabase/supabase-js";

const FALLBACK_SUPABASE_URL = "https://ltvwzkffmpudpjfjomrg.supabase.co";
const FALLBACK_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_bFWJkCQOyVU07PYMebjLgQ_yfb6bgQX";

function cleanEnv(value: string | undefined) {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  // Guard against values pasted with wrapping quotes from docs/shell examples.
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

export function publicDb(): SupabaseClient | null {
  const url = cleanEnv(process.env.NEXT_PUBLIC_SUPABASE_URL) || FALLBACK_SUPABASE_URL;
  const key = cleanEnv(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) || FALLBACK_SUPABASE_PUBLISHABLE_KEY;
  return createClient(url, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  });
}

export function adminDb(): SupabaseClient | null {
  const url = cleanEnv(process.env.SUPABASE_URL)
    || cleanEnv(process.env.NEXT_PUBLIC_SUPABASE_URL)
    || FALLBACK_SUPABASE_URL;
  const key = cleanEnv(process.env.SUPABASE_SECRET_KEY)
    || cleanEnv(process.env.SUPABASE_SERVICE_ROLE_KEY);
  if (!key) return null;

  const client = createClient(url, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  });

  // Billing code historically calls adminDb().auth.getUser(jwt). Keep that
  // surface, but verify member JWTs through a separate publishable-key auth
  // client. The privileged client remains untouched for PostgREST writes and
  // reads, matching Supabase's documented server-secret setup.
  const originalGetUser = client.auth.getUser.bind(client.auth);
  (client.auth as any).getUser = async (jwt?: string) => {
    if (!jwt) return originalGetUser();
    const authClient = publicDb();
    if (!authClient) {
      return {
        data: { user: null },
        error: { message: "member auth is not configured", status: 503 },
      };
    }
    return authClient.auth.getUser(jwt);
  };

  return client;
}

export const isDbConfigured = Boolean(
  (cleanEnv(process.env.NEXT_PUBLIC_SUPABASE_URL) || FALLBACK_SUPABASE_URL) &&
  (cleanEnv(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) || FALLBACK_SUPABASE_PUBLISHABLE_KEY)
);
