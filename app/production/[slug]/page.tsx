import { redirect } from "next/navigation";

export default async function ProductionDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  redirect(`/models/${slug}`);
}
