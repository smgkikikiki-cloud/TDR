import Link from "next/link";

export function SectionHeader({ kicker, title, href, linkLabel = "ดูทั้งหมด" }: { kicker?: string; title: string; href?: string; linkLabel?: string }) {
  return (
    <div className="sectionHeader">
      <div>
        {kicker && <div className="eyebrow">{kicker}</div>}
        <h2>{title}</h2>
      </div>
      {href && <Link href={href}>{linkLabel} →</Link>}
    </div>
  );
}
