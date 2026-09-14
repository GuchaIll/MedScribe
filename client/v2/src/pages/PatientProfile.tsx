import { useState } from "react";
import { LeftRail } from "@/components/clinical/LeftRail";
import {
  OverviewTab,
  BglAnalysisTab,
  MedicationsTab,
  LabResultsTab,
  MiniGoalsTab,
} from "@/components/clinical/PatientTabs";
import { Panel } from "@/components/clinical/_shared";
import { AllergiesEditor } from "@/components/patient/AllergiesEditor";
import { DietPanel } from "@/components/patient/DietPanel";
import { LabResultsCard } from "@/components/patient/LabResultsCard";
import { MedicalHistoryPanel } from "@/components/patient/MedicalHistoryPanel";
import { MedicationsCard } from "@/components/patient/MedicationsCard";
import { PatientHeaderCard } from "@/components/patient/PatientHeaderCard";
import { PatientTabsNav, PatientTopBar } from "@/components/patient/PatientChrome";
import { TimelinePanel } from "@/components/patient/TimelinePanel";
import {
  initialAllergies,
  initialLabs,
  initialMedications,
  tabs,
  type Allergy,
  type LabRow,
  type Med,
} from "@/data/patientMock";

const PatientProfile = () => {
  const [activeTab, setActiveTab] = useState(1);
  const [meds, setMeds] = useState<Med[]>(initialMedications);
  const [allergies, setAllergies] = useState<Allergy[]>(initialAllergies);
  const [labs, setLabs] = useState<LabRow[]>(initialLabs);

  return (
    <main className="relative min-h-screen w-full overflow-hidden p-2 md:p-4">
      <div className="pointer-events-none absolute -top-32 -right-20 h-[420px] w-[420px] rounded-full bg-gradient-to-br from-[hsl(38_100%_80%/0.5)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-[420px] w-[420px] rounded-full bg-gradient-to-tr from-[hsl(220_100%_82%/0.55)] to-transparent blur-3xl" />

      <div className="relative mx-auto flex min-h-[calc(100vh-1rem)] max-w-[1024px] overflow-hidden rounded-[2.25rem] glass-panel md:min-h-[calc(100vh-2rem)] xl:max-w-[1480px]">
        <LeftRail />

        <section className="flex min-w-0 flex-1 flex-col gap-5 pl-4 pr-[25px] pb-4 pt-4 md:pl-6 md:pr-[25px] md:pb-6 md:pt-6 lg:pl-8 lg:pr-[25px]">
          <PatientTopBar />
          <PatientTabsNav tabs={tabs} activeTab={activeTab} onSelect={setActiveTab} />

          {activeTab === 0 && <OverviewTab />}
          {activeTab === 2 && <BglAnalysisTab />}
          {activeTab === 3 && <MedicationsTab />}
          {activeTab === 4 && <LabResultsTab />}
          {activeTab === 5 && <MiniGoalsTab />}

          {activeTab === 1 && (
            <>
              <PatientHeaderCard />

              <div className="grid grid-cols-3 gap-5">
                <TimelinePanel />
                <MedicalHistoryPanel />
              </div>

              <div className="grid grid-cols-3 gap-5">
                <MedicationsCard meds={meds} setMeds={setMeds} />
                <DietPanel />
              </div>

              <div className="grid grid-cols-3 gap-5">
                <Panel>
                  <AllergiesEditor allergies={allergies} setAllergies={setAllergies} />
                </Panel>
                <LabResultsCard labs={labs} setLabs={setLabs} />
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
};

export default PatientProfile;
