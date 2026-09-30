"use client";

const STORAGE_KEY = "tdr-theme";

function currentTheme(): "light" | "dark" {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Toggles data-theme on <html>. Without a stored choice the page follows
 *  prefers-color-scheme (tokens.css); the first click stores an explicit choice.
 *  The stored value is applied before paint by the inline script in app/layout.tsx. */
export function ThemeToggle({ className }: { className?: string }) {
  return (
    <button
      type="button"
      className={className}
      aria-label="สลับธีมสว่าง/มืด"
      title="สลับธีม"
      onClick={() => {
        const next = currentTheme() === "dark" ? "light" : "dark";
        document.documentElement.dataset.theme = next;
        try { localStorage.setItem(STORAGE_KEY, next); } catch { /* private mode: the choice lasts for this page only */ }
      }}
    >
      ◐
    </button>
  );
}
