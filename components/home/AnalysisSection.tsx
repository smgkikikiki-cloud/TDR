import Link from "next/link";
import { Card } from "@/components/design";

/** Analysis Report (PAGES P01): the latest reports come from `analysis_reports`, which arrives with PR 13, and the old
 *  research table is not in production (blocker 3), so Home shows the approved empty state and does not read either. */
export function AnalysisSection() {
  return (
    <section className="tdr-home-blk tdr-home-blk--raised" aria-labelledby="home-analysis">
      <div className="tdr-wrap">
        <div className="tdr-home-head">
          <div>
            <div className="tdr-eyebrow" lang="en">Analysis Report</div>
            <h2 id="home-analysis" className="tdr-home-h2 tdr-home-h2--ink">รายงานวิเคราะห์</h2>
          </div>
          <Link className="tdr-home-more" href="/research">ดูรายงานทั้งหมด →</Link>
        </div>
        <Card tone="dashed" className="tdr-home-empty tdr-home-empty--center">
          <b className="tdr-card__title">ยังไม่มีรายงานที่เผยแพร่</b>
          <p className="tdr-home-muted">รายงานวิเคราะห์รายเดือนและเจาะลึกจะแสดงที่นี่ พร้อมป้ายระดับสมาชิกของแต่ละฉบับ</p>
        </Card>
      </div>
    </section>
  );
}
