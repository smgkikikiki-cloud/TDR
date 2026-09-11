"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import styles from "./catalog.module.css";

export function CatalogSort({ value }: { value: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  return <select
    className={styles.sortSelect}
    aria-label="เรียงลำดับรถ"
    value={value}
    onChange={(event) => {
      const params = new URLSearchParams(searchParams.toString());
      if (event.target.value === "recommended") params.delete("sort");
      else params.set("sort", event.target.value);
      router.push(`${pathname}${params.size ? `?${params.toString()}` : ""}`);
    }}
  >
    <option value="recommended">เรียง: แนะนำ</option>
    <option value="new">ใหม่ล่าสุด</option>
    <option value="price-asc">ราคา ต่ำ → สูง</option>
    <option value="price-desc">ราคา สูง → ต่ำ</option>
    <option value="az">A – Z</option>
  </select>;
}
