import { useState } from "react";
import { Edit3, FileText, Plus, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Panel, SectionHeader, toneClasses } from "@/components/clinical/_shared";
import { adherenceWeeks, type Med } from "@/data/patientMock";

const emptyMed: Med = { name: "", sub: "", status: "Adherent", statusTone: "emerald" };

const toneToStatus = (tone: Med["statusTone"]): string =>
  tone === "emerald" ? "Adherent" : tone === "amber" ? "Somehow adherent" : "Not adherent";

export const MedicationsCard = ({
  meds,
  setMeds,
}: {
  meds: Med[];
  setMeds: (m: Med[]) => void;
}) => {
  const [editingMedIdx, setEditingMedIdx] = useState<number | null>(null);
  const [medDraft, setMedDraft] = useState<Med>(emptyMed);

  const startEditMed = (i: number) => {
    setEditingMedIdx(i);
    setMedDraft(meds[i]);
  };

  const saveMed = () => {
    if (!medDraft.name.trim()) {
      toast.error("Medication name required");
      return;
    }
    if (editingMedIdx === -1) {
      setMeds([...meds, medDraft]);
      toast.success("Medication added");
    } else if (editingMedIdx !== null) {
      const next = [...meds];
      next[editingMedIdx] = medDraft;
      setMeds(next);
      toast.success("Medication updated");
    }
    setEditingMedIdx(null);
  };

  const deleteMed = (i: number) => {
    setMeds(meds.filter((_, idx) => idx !== i));
    toast.success("Medication removed");
  };

  return (
    <Panel className="col-span-2">
      <SectionHeader
        icon={FileText}
        title="Medications"
        action={
          <button
            onClick={() => {
              setEditingMedIdx(-1);
              setMedDraft(emptyMed);
            }}
            className="glass-chip flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium"
          >
            <Plus className="h-3 w-3" /> Add
          </button>
        }
      />

      {editingMedIdx !== null && (
        <div className="mb-4 rounded-2xl border border-white/50 bg-white/40 p-3.5 backdrop-blur-md">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-foreground/55">
            {editingMedIdx === -1 ? "Add medication" : "Edit medication"}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input
              placeholder="Name"
              value={medDraft.name}
              onChange={(e) => setMedDraft({ ...medDraft, name: e.target.value })}
              className="glass-chip rounded-xl px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-foreground/20"
            />
            <input
              placeholder="Dosage / sub"
              value={medDraft.sub}
              onChange={(e) => setMedDraft({ ...medDraft, sub: e.target.value })}
              className="glass-chip rounded-xl px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-foreground/20"
            />
            <select
              value={medDraft.statusTone}
              onChange={(e) => {
                const tone = e.target.value as Med["statusTone"];
                setMedDraft({ ...medDraft, statusTone: tone, status: toneToStatus(tone) });
              }}
              className="glass-chip col-span-2 rounded-xl px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-foreground/20"
            >
              <option value="emerald">Adherent</option>
              <option value="amber">Somehow adherent</option>
              <option value="rose">Not adherent</option>
            </select>
          </div>
          <div className="mt-2 flex justify-end gap-1.5">
            <button
              onClick={() => setEditingMedIdx(null)}
              className="glass-chip flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium text-foreground/60"
            >
              <X className="h-3 w-3" /> Cancel
            </button>
            <button
              onClick={saveMed}
              className="flex items-center gap-1 rounded-full bg-foreground px-3 py-1 text-[12px] font-medium text-background"
            >
              <Save className="h-3 w-3" /> Save
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-[1.6fr_1fr_0.8fr_0.6fr] gap-3 border-b border-white/40 pb-2 text-[11px] uppercase tracking-wide text-foreground/50">
        <span>Name ↓</span>
        <span>Status</span>
        <span>Assign by</span>
        <span className="text-right">Actions</span>
      </div>
      <ul className="divide-y divide-white/40">
        {meds.map((m, i) => (
          <li
            key={i}
            className="grid grid-cols-[1.6fr_1fr_0.8fr_0.6fr] items-center gap-3 py-3 text-[12.5px]"
          >
            <div className="flex items-center gap-2.5">
              <div className="h-8 w-8 rounded-lg bg-white/70 border border-white/60" />
              <div>
                <div className="font-medium">{m.name}</div>
                <div className="text-[11px] text-foreground/50">{m.sub}</div>
              </div>
            </div>
            <span
              className={`inline-flex w-fit rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${toneClasses[m.statusTone]}`}
            >
              {m.status}
            </span>
            <span className="font-medium">Patient</span>
            <div className="flex justify-end gap-1">
              <button
                onClick={() => startEditMed(i)}
                className="glass-chip flex h-7 w-7 items-center justify-center rounded-full"
                aria-label="Edit"
              >
                <Edit3 className="h-3 w-3 text-foreground/60" />
              </button>
              <button
                onClick={() => deleteMed(i)}
                className="glass-chip flex h-7 w-7 items-center justify-center rounded-full hover:bg-rose-100/60"
                aria-label="Delete"
              >
                <Trash2 className="h-3 w-3 text-rose-600" />
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-5 rounded-2xl border border-white/50 bg-white/30 p-4 backdrop-blur-md">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-[12.5px] font-semibold">Adherence — last 4 weeks</div>
          <div className="flex items-center gap-2 text-[10.5px] text-foreground/55">
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-emerald-400" /> Taken</span>
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-rose-300" /> Missed</span>
          </div>
        </div>
        <div className="space-y-1.5">
          {adherenceWeeks.map((week, wi) => (
            <div key={wi} className="flex items-center gap-2">
              <span className="w-12 text-[10.5px] text-foreground/50">W{wi + 1}</span>
              <div className="flex flex-1 gap-1">
                {week.map((d, di) => (
                  <div
                    key={di}
                    className={`h-5 flex-1 rounded ${d ? "bg-emerald-400/70" : "bg-rose-300/70"}`}
                    title={d ? "Taken" : "Missed"}
                  />
                ))}
              </div>
            </div>
          ))}
          <div className="mt-1 flex items-center gap-2">
            <span className="w-12" />
            <div className="flex flex-1 justify-between text-[10px] text-foreground/45">
              {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
                <span key={i} className="flex-1 text-center">{d}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
};
