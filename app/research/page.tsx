export const dynamic = "force-dynamic";

/**
 * Layer 3: analysis written and interpreted by a person, published as a piece.
 *
 * Nothing is published yet. The page says so, in the same way /news does,
 * rather than dressing the gap up as "coming soon" or filling it with a
 * placeholder — an empty section that admits it is empty costs nothing, while
 * a fake one costs the reader's trust in every number elsewhere on the site.
 */
export default async function ResearchPage() {
  const pieces: Array<{ id: string; title: string; published: string; summary: string }> = [];

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
          {pieces.map((p) => (
            <article key={p.id}>
              <time>{p.published}</time>
              <div><b>{p.title}</b><p>{p.summary}</p></div>
            </article>
          ))}
        </div>
      ) : (
        <div className="sfEmpty"><b>ยังไม่มีบทวิเคราะห์เผยแพร่</b></div>
      )}
    </section>

  </>;
}
