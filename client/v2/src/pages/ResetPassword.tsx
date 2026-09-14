import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { toast } from "sonner";
import { Lock, ArrowRight } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";

const passwordSchema = z.string().min(6, "Min 6 characters").max(72);

const ResetPassword = () => {
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Supabase parses the recovery token from the URL hash automatically.
    const { data: sub } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") setReady(true);
    });
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) setReady(true);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    try {
      const parsed = passwordSchema.parse(password);
      setBusy(true);
      const { error } = await supabase.auth.updateUser({ password: parsed });
      if (error) throw error;
      await supabase.auth.signOut();
      toast.success("Password updated — please sign in");
      navigate("/auth", { replace: true });
    } catch (err: any) {
      if (err?.name === "ZodError") toast.error(err.errors?.[0]?.message ?? "Invalid input");
      else toast.error(err?.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="relative flex min-h-screen w-full items-center justify-center overflow-hidden p-6">
      <div className="pointer-events-none absolute -top-32 -right-20 h-[480px] w-[480px] rounded-full bg-gradient-to-br from-[hsl(38_100%_80%/0.55)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-[480px] w-[480px] rounded-full bg-gradient-to-tr from-[hsl(220_100%_82%/0.6)] to-transparent blur-3xl" />

      <section className="relative w-full max-w-[420px]">
        <div className="glass-panel rounded-[2rem] p-8">
          <header className="mb-7 text-center">
            <h1 className="text-2xl font-semibold tracking-tight">Set a new password</h1>
            <p className="mt-1 text-sm text-foreground/55">
              {ready ? "Choose a strong password to continue" : "Verifying reset link…"}
            </p>
          </header>

          <form onSubmit={handleSubmit} className="space-y-3">
            <label className="glass-chip flex h-12 items-center gap-3 rounded-2xl px-4 focus-within:ring-2 focus-within:ring-foreground/15">
              <span className="text-foreground/45">
                <Lock className="h-4 w-4" />
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="New password"
                autoComplete="new-password"
                required
                className="flex-1 bg-transparent text-sm text-foreground placeholder:text-foreground/40 focus:outline-none"
              />
            </label>

            <button
              type="submit"
              disabled={busy || !ready}
              className="mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-full bg-primary text-sm font-medium text-primary-foreground shadow-[0_10px_30px_-10px_hsl(var(--primary)/0.55)] transition-all hover:scale-[1.01] disabled:opacity-60"
            >
              {busy ? "Saving…" : "Update password"}
              {!busy && <ArrowRight className="h-4 w-4" />}
            </button>
          </form>
        </div>
      </section>
    </main>
  );
};

export default ResetPassword;
