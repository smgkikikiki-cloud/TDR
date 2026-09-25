function normalizeBase(raw: string): string {
  const value = raw.trim();
  if (!value) return "http://localhost:3000";
  const withProtocol = /^https?:\/\//i.test(value) ? value : `https://${value}`;
  return withProtocol.replace(/\/+$/, "");
}

/**
 * One canonical origin for metadata, sitemap and feeds.
 *
 * Vercel exposes VERCEL_PROJECT_PRODUCTION_URL in production. A custom domain
 * can override it with NEXT_PUBLIC_SITE_URL (preferred) or SITE_URL without
 * changing code. localhost is intentionally only the final development
 * fallback.
 */
export function siteUrl(): string {
  return normalizeBase(
    process.env.NEXT_PUBLIC_SITE_URL
      || process.env.SITE_URL
      || process.env.VERCEL_PROJECT_PRODUCTION_URL
      || process.env.VERCEL_URL
      || "http://localhost:3000",
  );
}

export function absoluteUrl(path: string): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${siteUrl()}${cleanPath}`;
}
