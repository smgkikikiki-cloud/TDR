import { NewsForm } from "@/components/admin/NewsForm";
import { loadNewsFormOptions } from "../options";

export const dynamic = "force-dynamic";

export default async function NewNewsArticle() {
  const { tags, others } = await loadNewsFormOptions(null);
  return <div className="adminEditor">
    <div className="adminHeader"><div><small>NEWS</small><h1>เขียนข่าวใหม่</h1></div></div>
    <NewsForm tags={tags} others={others} />
  </div>;
}
