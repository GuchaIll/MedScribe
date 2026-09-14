import { useState } from "react";
import { Edit3, Plus, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import type { LabRow } from "@/data/patientMock";

const emptyLab: LabRow = { test: "", value: "", unit: "", ref: "", date: "" };

export const LabsTable = ({
  labs,
  setLabs,
}: {
  labs: LabRow[];
  setLabs: (l: LabRow[]) => void;
}) => {
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState<LabRow>(emptyLab);
  const [adding, setAdding] = useState(false);

  const startEdit = (i: number) => {
    setEditingIdx(i);
    setAdding(false);
    setDraft(labs[i]);
  };

  const startAdd = () => {
    setAdding(true);
    setEditingIdx(null);
    setDraft(emptyLab);
  };

  const cancel = () => {
    setEditingIdx(null);
    setAdding(false);
    setDraft(emptyLab);
  };

  const save = () => {
    if (!draft.test.trim() || !draft.value.trim()) {
      toast.error("Test name and value required");
      return;
    }
    if (adding) {
      setLabs([...labs, draft]);
      toast.success("Lab result added");
    } else if (editingIdx !== null) {
      const next = [...labs];
      next[editingIdx] = draft;
      setLabs(next);
      toast.success("Lab result updated");
    }
    cancel();
  };

  const remove = (i: number) => {
    setLabs(labs.filter((_, idx) => idx !== i));
    toast.success("Lab result removed");
  };

  const DraftRow = (
    <li className="grid grid-cols-[1.2fr_0.7fr_0.6fr_0.7fr_0.7fr_0.5fr] items-center gap-2 rounded-xl border border-white/60 bg-white/40 px-2 py-2 text-[12.5px] backdrop-blur-md">
      <input
        placeholder="Test"
        value={draft.test}
        onChange={(e) => setDraft({ ...draft, test: e.target.value })}
        className="glass-chip rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-foreground/20"
      />
      <input
        placeholder="Value"
        value={draft.value}
        onChange={(e) => setDraft({ ...draft, value: e.target.value })}
        className="glass-chip rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-foreground/20"
      />
      <input
        placeholder="Unit"
        value={draft.unit}
        onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
        className="glass-chip rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-foreground/20"
      />
      <input
        placeholder="Ref"
        value={draft.ref}
        onChange={(e) => setDraft({ ...draft, ref: e.target.value })}
        className="glass-chip rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-foreground/20"
      />
      <input
        placeholder="Date"
        value={draft.date}
        onChange={(e) => setDraft({ ...draft, date: e.target.value })}
        className="glass-chip rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-foreground/20"
      />
      <div className="flex justify-end gap-1">
        <button
          onClick={cancel}
          className="glass-chip flex h-7 w-7 items-center justify-center rounded-full"
          aria-label="Cancel"
        >
          <X className="h-3 w-3" />
        </button>
        <button
          onClick={save}
          className="flex h-7 w-7 items-center justify-center rounded-full bg-foreground text-background"
          aria-label="Save"
        >
          <Save className="h-3 w-3" />
        </button>
      </div>
    </li>
  );

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button
          onClick={startAdd}
          className="glass-chip flex items-center gap-1 rounded-full px-3 py-1 text-[12px] font-medium"
        >
          <Plus className="h-3 w-3" /> Add result
        </button>
      </div>
      <div className="grid grid-cols-[1.2fr_0.7fr_0.6fr_0.7fr_0.7fr_0.5fr] gap-2 border-b border-white/40 px-2 pb-2 text-[11px] uppercase tracking-wide text-foreground/50">
        <span>Test</span>
        <span>Value</span>
        <span>Unit</span>
        <span>Reference</span>
        <span>Date</span>
        <span className="text-right">Actions</span>
      </div>
      <ul className="space-y-1">
        {labs.map((r, i) =>
          editingIdx === i ? (
            <div key={i}>{DraftRow}</div>
          ) : (
            <li
              key={i}
              className="grid grid-cols-[1.2fr_0.7fr_0.6fr_0.7fr_0.7fr_0.5fr] items-center gap-2 px-2 py-2.5 text-[12.5px]"
            >
              <span className="font-medium">{r.test}</span>
              <span className="font-semibold">{r.value}</span>
              <span className="text-foreground/55">{r.unit}</span>
              <span className="text-foreground/55">{r.ref}</span>
              <span className="text-foreground/55">{r.date}</span>
              <div className="flex justify-end gap-1">
                <button
                  onClick={() => startEdit(i)}
                  className="glass-chip flex h-7 w-7 items-center justify-center rounded-full"
                  aria-label="Edit"
                >
                  <Edit3 className="h-3 w-3 text-foreground/60" />
                </button>
                <button
                  onClick={() => remove(i)}
                  className="glass-chip flex h-7 w-7 items-center justify-center rounded-full hover:bg-rose-100/60"
                  aria-label="Delete"
                >
                  <Trash2 className="h-3 w-3 text-rose-600" />
                </button>
              </div>
            </li>
          ),
        )}
        {adding && DraftRow}
      </ul>
    </div>
  );
};
