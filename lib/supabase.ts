import { createClient, SupabaseClient } from "@supabase/supabase-js";

const FALLBACK_SUPABASE_URL = "https://ltvwzkffmpudpjfjomrg.supabase.co";
const FALLBACK_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_bFWJkCQOyVU07PYMebjLgQ_yfb6bgQX";

export function publicDb(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || FALLBACK_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || FALLBACK_SUPABASE_PUBLISHABLE_KEY;
  return createClient(url, key, { auth: { persistSession: false } });
}

export function adminDb(): SupabaseClient | null {
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || FALLBACK_SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) return null;

  const client = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  // Member requests arrive with a user access-token JWT. Validate that token
  // against the Auth server with the public API key, while keeping the secret
  // key exclusively for privileged database access. This avoids coupling user
  // JWT verification to the admin client's API-key authentication semantics.
  const originalGetUser = client.auth.getUser.bind(client.auth);
  (client.auth as any).getUser = async (jwt?: string) => {
    if (!jwt) return originalGetUser();

    const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || FALLBACK_SUPABASE_PUBLISHABLE_KEY;
    const response = await fetch(`${url}/auth/v1/user`, {
      method: "GET",
      headers: {
        apikey: publishableKey,
        Authorization: `Bearer ${jwt}`,
      },
      cache: "no-store",
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      return {
        data: { user: null },
        error: {
          message: body?.msg || body?.message || "invalid member session",
          status: response.status,
        },
      };
    }

    return { data: { user: await response.json() }, error: null };
  };

  return client;
}

export const isDbConfigured = Boolean(
  (process.env.NEXT_PUBLIC_SUPABASE_URL || FALLBACK_SUPABASE_URL) &&
  (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || FALLBACK_SUPABASE_PUBLISHABLE_KEY)
);
