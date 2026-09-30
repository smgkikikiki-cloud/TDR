import Link from "next/link";

const ENTRIES = [
  { n: "01", href: "/market", title: "Automotive Intelligence", text: "ยอดจดทะเบียนและส่วนแบ่งตลาด" },
  { n: "02", href: "/models", title: "Vehicle Database", text: "สเปก ราคา รุ่นย่อย" },
  { n: "03", href: "/compare", title: "Compare Specs", text: "เทียบสเปกตรงรุ่นย่อย" },
  { n: "04", href: "/research", title: "Analysis Report", text: "บทวิเคราะห์รายเดือนและเจาะลึก" },
] as const;

/** The four shortcut cards, in menu order (PAGES P01). Nothing on them is computed. */
export function EntryCards() {
  return (
    <nav className="tdr-home-entries" aria-label="ทางลัด">
      {ENTRIES.map((e) => (
        <Link key={e.n} href={e.href} className="tdr-home-entry">
          <span className="tdr-home-entry__k">{e.n}<i aria-hidden="true">→</i></span>
          <b>{e.title}</b>
          <small>{e.text}</small>
        </Link>
      ))}
    </nav>
  );
}
