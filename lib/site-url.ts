function normalizeBase(raw: string): string {
  const value = raw.trim();
  if (!value) return "http://localhost:3000";
  const withProtocol = /^https?:\/\//i.test(value) ? value : `https://${value}`;
  return withProtocol.replace(/\/+$/, "");
}

/**
 * One canonical origin for metadata, sitemap and feeds.
 *
 * TDR_APP_URL is already the repo's canonical production origin (used by
 * billing redirects), so SEO surfaces reuse it rather than inventing a second
 * required production setting. The other names remain optional overrides for
 * deployments that already expose a public-site URL explicitly.
 */
export function siteUrl(): string {
  return normalizeBase(
    process.env.NEXT_PUBLIC_SITE_URL
      || process.env.SITE_URL
      || process.env.TDR_APP_URL
      || process.env.VERCEL_PROJECT_PRODUCTION_URL
      || process.env.VERCEL_URL
      || "http://localhost:3000",
  );
}

export function absoluteUrl(path: string): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${siteUrl()}${cleanPath}`;
}
