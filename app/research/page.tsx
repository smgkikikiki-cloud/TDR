import Link from "next/link";
import { getPublishedResearchArticles } from "@/lib/research";

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
 */
export default async function ResearchPage() {
  const pieces = await getPublishedResearchArticles(100);

  return <>
    <section className="sfBlock">
      <div className="sfZoneHead">
        <div>
          <div className="sfEyebrow">บทวิเคราะห์เชิงลึก</div>
          <h1>บทวิเคราะห์ตลาดรถยนต์ไทย</h1>
        </div>
        <span>{pieces.length} ชิ้น</span>
      </div>
      {pieces.length ? (
        <div className="sfNewsList">
          {pieces.map((piece) => (
            <article key={piece.id}>
              <time>{piece.publishedAt.slice(0, 10)}</time>
              <div>
                <Link href={`/research/${piece.slug}`}><b>{piece.titleTh}</b></Link>
                <p>{piece.summaryTh}</p>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="sfEmpty"><b>ยังไม่มีบทวิเคราะห์เผยแพร่</b></div>
      )}
    </section>
  </>;
}
