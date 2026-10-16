import { Card, PageHead } from "@/components/design";
import { getPublishedResearchArticles } from "@/lib/research";
import "./research.css";

export const dynamic = "force-dynamic";

/**
 * Layer 4: analysis written and interpreted by a person, published as a
 * piece -- app/admin/(secure)/research authors it, app/api/research/read
 * is where a signed-in member unlocks the full text.
 *
 * Everyone sees this list and every summary on it; nobody unlocks the full
 * text without an account. An empty list stays an honest empty state --
 * "ยังไม่มีบทวิเคราะห์เผยแพร่" costs nothing, while a fake placeholder piece
 * costs the reader's trust in every real number elsewhere on the site.
 *
 * Presentation only (design graft, tokens + shared components): the data path is unchanged.
 * The preview carries no tier, image or category field, so none is shown.
 */
export default async function ResearchPage() {
  let pieces: Awaited<ReturnType<typeof getPublishedResearchArticles>> = [];
  let failed = false;
  try {
    pieces = await getPublishedResearchArticles(100);
  } catch {
    failed = true;
  }

  return <div className="designPage tdr-research">
    <div className="tdr-wrap">
      <PageHead
        eyebrow="บทวิเคราะห์เชิงลึก"
        title="บทวิเคราะห์ตลาดรถยนต์ไทย"
        lead="บทวิเคราะห์ที่เขียนและตีความโดยทีมงาน ทุกคนอ่านสรุปได้ ฉบับเต็มต้องมีบัญชี"
        aside={!failed && pieces.length ? <span className="tdr-research-count">{pieces.length} ชิ้น</span> : undefined}
      />

      {failed ? (
        <Card tone="dashed" className="tdr-research-state">
          <div role="alert">
            <b className="tdr-card__title">บทวิเคราะห์</b>
            <p>โหลดรายการไม่สำเร็จ · <a href="/research">ลองอีกครั้ง</a></p>
          </div>
        </Card>
      ) : pieces.length ? (
        <>
          <Card as="article" href={`/research/${pieces[0].slug}`} tone="raised" className="tdr-research-feature">
            <div className="tdr-research-item">
              <time dateTime={pieces[0].publishedAt}>{pieces[0].publishedAt.slice(0, 10)} · ล่าสุด</time>
              <h2>{pieces[0].titleTh}</h2>
              <p>{pieces[0].summaryTh}</p>
            </div>
          </Card>
          {pieces.length > 1 ? (
            <ul className="tdr-research-grid" aria-label="บทวิเคราะห์ก่อนหน้า">
              {pieces.slice(1).map((piece) => (
                <li key={piece.id}>
                  <Card href={`/research/${piece.slug}`}>
                    <div className="tdr-research-item">
                      <time dateTime={piece.publishedAt}>{piece.publishedAt.slice(0, 10)}</time>
                      <h3>{piece.titleTh}</h3>
                      <p>{piece.summaryTh}</p>
                    </div>
                  </Card>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <Card tone="dashed" className="tdr-research-state">
          <b className="tdr-card__title">ยังไม่มีบทวิเคราะห์เผยแพร่</b>
          <p>เมื่อมีบทวิเคราะห์ใหม่ หน้านี้จะแสดงทันที</p>
        </Card>
      )}
    </div>
  </div>;
}
