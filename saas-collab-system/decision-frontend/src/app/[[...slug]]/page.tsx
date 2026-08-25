import { DecisionWorkspace } from "../../components/decision-workspace";

export default async function Page({ searchParams }: { searchParams: Promise<{ embed?: string }> }) {
  const query = await searchParams;
  return <DecisionWorkspace embedded={query.embed === "1"} />;
}
