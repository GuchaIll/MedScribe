import { useState } from "react";
import { AlertTriangle, Plus, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { SectionHeader, toneClasses } from "@/components/clinical/_shared";
import type { Allergy } from "@/data/patientMock";

const sevTone = (s: Allergy["severity"]) =>
  s === "Severe" ? "rose" : s === "Moderate" ? "amber" : "emerald";

export const AllergiesEditor = ({
  allergies,
  setAllergies,
}: {
  allergies: Allergy[];
  setAllergies: (a: Allergy[]) => void;
}) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Allergy[]>(allergies);
  const [newName, setNewName] = useState("");

  const start = () => {
    setDraft(allergies);
    setEditing(true);
  };
  const save = () => {
    setAllergies(draft);
    setEditing(false);
    toast.success("Allergies updated");
  };

  return (
    <>
      <SectionHeader
        icon={AlertTriangle}
        title="Allergies"
        action={
          editing ? (
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setEditing(false)}
                className="glass-chip flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium text-foreground/60"
              >
                <X className="h-3 w-3" /> Cancel
              </button>
              <button
                onClick={save}
                className="flex items-center gap-1 rounded-full bg-foreground px-3 py-1 text-[12px] font-medium text-background"
              >
                <Save className="h-3 w-3" /> Save
              </button>
            </div>
          ) : (
            <button
              onClick={start}
              className="text-[13px] font-medium text-foreground/50 hover:text-foreground"
            >
              Edit
            </button>
          )
        }
      />
      <ul className="space-y-2">
        {(editing ? draft : allergies).map((a, i) => (
          <li key={i} className="glass-chip flex items-center gap-2 rounded-2xl px-3 py-2 text-[12.5px]">
            {editing ? (
              <>
                <input
                  value={a.name}
                  onChange={(e) => {
                    const next = [...draft];
                    next[i] = { ...a, name: e.target.value };
                    setDraft(next);
                  }}
                  className="flex-1 rounded-lg bg-white/60 px-2 py-1 outline-none focus:ring-2 focus:ring-foreground/20"
                />
                <select
                  value={a.severity}
                  onChange={(e) => {
                    const next = [...draft];
                    next[i] = { ...a, severity: e.target.value as Allergy["severity"] };
                    setDraft(next);
                  }}
                  className="rounded-lg bg-white/60 px-2 py-1 text-[11.5px] outline-none"
                >
                  <option>Mild</option>
                  <option>Moderate</option>
                  <option>Severe</option>
                </select>
                <button
                  onClick={() => setDraft(draft.filter((_, idx) => idx !== i))}
                  className="text-rose-600"
                  aria-label="Remove allergy"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            ) : (
              <>
                <span className="flex-1 font-medium">{a.name}</span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${toneClasses[sevTone(a.severity)]}`}
                >
                  {a.severity}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
      {editing && (
        <div className="mt-2 flex gap-1.5">
          <input
            placeholder="Add allergy…"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="glass-chip flex-1 rounded-xl px-3 py-1.5 text-[12.5px] outline-none focus:ring-2 focus:ring-foreground/20"
          />
          <button
            onClick={() => {
              if (!newName.trim()) return;
              setDraft([...draft, { name: newName.trim(), severity: "Mild" }]);
              setNewName("");
            }}
            className="glass-chip flex items-center gap-1 rounded-xl px-3 py-1.5 text-[12px] font-medium"
          >
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>
      )}
    </>
  );
};
