import { ScenarioWorkbench } from "@/components/academy/scenario-workbench";

export default async function AcademyScenarioPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ScenarioWorkbench scenarioId={id.toUpperCase()} />;
}
