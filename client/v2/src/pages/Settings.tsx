import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Save, User as UserIcon, ImageIcon } from "lucide-react";
import { z } from "zod";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/hooks/useAuth";
import { useProfile } from "@/hooks/useProfile";
import { LeftRail } from "@/components/clinical/LeftRail";

const nameSchema = z.string().trim().min(1, "Name required").max(80);
const urlSchema = z
  .string()
  .trim()
  .max(500)
  .url("Must be a valid URL")
  .refine((u) => u.startsWith("https://"), "Avatar URL must use https://")
  .or(z.literal(""));

const Settings = () => {
  const { user } = useAuth();
  const { profile, refresh } = useProfile();
  const [name, setName] = useState("");
  const [avatar, setAvatar] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setName(profile?.display_name ?? "");
    setAvatar(profile?.avatar_url ?? "");
  }, [profile]);

  const initial =
    (profile?.display_name?.[0] ?? user?.email?.[0] ?? "?").toUpperCase();

  const save = async () => {
    if (!user) return;
    try {
      const parsedName = nameSchema.parse(name);
      const parsedAvatar = urlSchema.parse(avatar);
      setBusy(true);
      const { error } = await supabase
        .from("profiles")
        .update({
          display_name: parsedName,
          avatar_url: parsedAvatar || null,
        })
        .eq("id", user.id);
      if (error) throw error;
      toast.success("Profile updated");
      refresh();
    } catch (err: any) {
      if (err?.name === "ZodError") toast.error(err.errors?.[0]?.message ?? "Invalid input");
      else toast.error(err?.message ?? "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="relative min-h-screen w-full overflow-hidden p-4">
      <div className="pointer-events-none absolute -top-32 -right-20 h-[420px] w-[420px] rounded-full bg-gradient-to-br from-[hsl(38_100%_80%/0.5)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-[420px] w-[420px] rounded-full bg-gradient-to-tr from-[hsl(220_100%_82%/0.55)] to-transparent blur-3xl" />

      <div className="relative mx-auto flex h-[calc(100vh-2rem)] max-w-[1480px] overflow-hidden rounded-[2.25rem] glass-panel">
        <LeftRail />

        <section className="flex flex-1 flex-col gap-6 overflow-y-auto px-10 py-8">
          <header className="flex items-center justify-between">
            <div>
              <Link
                to="/"
                className="mb-3 inline-flex items-center gap-1.5 text-xs font-medium text-foreground/60 hover:text-foreground"
              >
                <ArrowLeft className="h-3 w-3" /> Back
              </Link>
              <h1 className="text-3xl font-semibold tracking-tight">Profile settings</h1>
              <p className="mt-1 text-sm text-foreground/55">
                Manage how you appear across your workspace
              </p>
            </div>
            <button
              onClick={save}
              disabled={busy}
              className="flex h-11 items-center gap-2 rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground shadow-[0_10px_30px_-10px_hsl(var(--primary)/0.55)] transition-transform hover:scale-[1.02] disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {busy ? "Saving…" : "Save changes"}
            </button>
          </header>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="glass-panel flex flex-col items-center gap-4 rounded-[1.75rem] p-8 lg:col-span-1">
              <div className="relative">
                <div className="glass-chip flex h-28 w-28 items-center justify-center overflow-hidden rounded-full text-2xl font-semibold text-foreground/70">
                  {avatar ? (
                    <img
                      src={avatar}
                      alt="Avatar preview"
                      className="h-full w-full object-cover"
                      onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
                    />
                  ) : (
                    initial
                  )}
                </div>
              </div>
              <div className="text-center">
                <p className="text-base font-semibold">{name || "Your name"}</p>
                <p className="text-xs text-foreground/55">{user?.email}</p>
              </div>
            </div>

            <div className="glass-panel flex flex-col gap-5 rounded-[1.75rem] p-8 lg:col-span-2">
              <Field
                label="Display name"
                icon={<UserIcon className="h-4 w-4" />}
                value={name}
                onChange={setName}
                placeholder="Dr. Jane Doe"
              />
              <Field
                label="Avatar URL"
                icon={<ImageIcon className="h-4 w-4" />}
                value={avatar}
                onChange={setAvatar}
                placeholder="https://…"
              />
              <p className="text-xs text-foreground/50">
                Paste a link to a square image (PNG or JPG) hosted anywhere on the web.
              </p>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
};

const Field = ({
  label,
  icon,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  icon: React.ReactNode;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) => (
  <label className="flex flex-col gap-2">
    <span className="text-xs font-medium uppercase tracking-wider text-foreground/55">
      {label}
    </span>
    <span className="glass-chip flex h-12 items-center gap-3 rounded-2xl px-4 focus-within:ring-2 focus-within:ring-foreground/15">
      <span className="text-foreground/45">{icon}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="flex-1 bg-transparent text-sm text-foreground placeholder:text-foreground/40 focus:outline-none"
      />
    </span>
  </label>
);

export default Settings;
