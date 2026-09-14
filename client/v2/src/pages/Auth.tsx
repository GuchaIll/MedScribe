import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { z } from "zod";
import { toast } from "sonner";
import { Stethoscope, Mail, Lock, User as UserIcon, ArrowRight, ArrowLeft } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

const emailSchema = z.string().trim().email("Enter a valid email").max(255);
const passwordSchema = z.string().min(6, "Min 6 characters").max(72);
const nameSchema = z.string().trim().min(1, "Name required").max(80);

type Mode = "signin" | "signup" | "forgot";

const Auth = () => {
  const { session, loading } = useAuth();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [mode, setMode] = useState<Mode>("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setName("");
    setPassword("");
  }, [mode]);

  if (!loading && session) return <Navigate to={from} replace />;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;

    try {
      const parsedEmail = emailSchema.parse(email);
      setBusy(true);

      if (mode === "forgot") {
        const { error } = await supabase.auth.resetPasswordForEmail(parsedEmail, {
          redirectTo: `${window.location.origin}/reset-password`,
        });
        if (error) throw error;
        toast.success("Reset email sent — check your inbox");
        setMode("signin");
        return;
      }

      const parsedPassword = passwordSchema.parse(password);

      if (mode === "signup") {
        const parsedName = nameSchema.parse(name);
        const redirectUrl = `${window.location.origin}/`;
        const { error } = await supabase.auth.signUp({
          email: parsedEmail,
          password: parsedPassword,
          options: {
            emailRedirectTo: redirectUrl,
            data: { display_name: parsedName },
          },
        });
        if (error) throw error;
        await supabase.auth.signOut();
        toast.success("Account created — please sign in");
        setMode("signin");
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: parsedEmail,
          password: parsedPassword,
        });
        if (error) throw error;
        toast.success("Welcome back");
      }
    } catch (err: any) {
      if (err?.name === "ZodError") {
        toast.error(err.errors?.[0]?.message ?? "Invalid input");
      } else {
        toast.error(err?.message ?? "Something went wrong");
      }
    } finally {
      setBusy(false);
    }
  };

  const title =
    mode === "signin" ? "Welcome back" : mode === "signup" ? "Create account" : "Reset password";
  const subtitle =
    mode === "signin"
      ? "Sign in to your clinical workspace"
      : mode === "signup"
      ? "Start transcribing in seconds"
      : "We'll send you a reset link";

  return (
    <main className="relative flex min-h-screen w-full items-center justify-center overflow-hidden p-6">
      <div className="pointer-events-none absolute -top-32 -right-20 h-[480px] w-[480px] rounded-full bg-gradient-to-br from-[hsl(38_100%_80%/0.55)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-[480px] w-[480px] rounded-full bg-gradient-to-tr from-[hsl(220_100%_82%/0.6)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-[360px] w-[360px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-br from-[hsl(280_70%_88%/0.45)] to-transparent blur-3xl" />

      <section className="relative w-full max-w-[420px]">
        <div className="glass-panel rounded-[2rem] p-8">
          <header className="mb-7 flex flex-col items-center gap-3 text-center">
            <div className="glass-chip flex h-12 w-12 items-center justify-center rounded-full">
              <Stethoscope className="h-5 w-5 text-foreground/80" strokeWidth={1.8} />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
              <p className="mt-1 text-sm text-foreground/55">{subtitle}</p>
            </div>
          </header>

          {mode !== "forgot" && (
            <div className="glass-chip mb-6 grid grid-cols-2 gap-1 rounded-full p-1">
              {(["signin", "signup"] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    "rounded-full px-4 py-2 text-sm font-medium transition-all",
                    mode === m
                      ? "bg-primary text-primary-foreground shadow-[0_6px_18px_-6px_hsl(var(--primary)/0.5)]"
                      : "text-foreground/60 hover:text-foreground"
                  )}
                >
                  {m === "signin" ? "Sign in" : "Sign up"}
                </button>
              ))}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            {mode === "signup" && (
              <Field
                icon={<UserIcon className="h-4 w-4" />}
                type="text"
                placeholder="Full name"
                value={name}
                onChange={setName}
                autoComplete="name"
              />
            )}
            <Field
              icon={<Mail className="h-4 w-4" />}
              type="email"
              placeholder="you@clinic.com"
              value={email}
              onChange={setEmail}
              autoComplete="email"
            />
            {mode !== "forgot" && (
              <Field
                icon={<Lock className="h-4 w-4" />}
                type="password"
                placeholder="Password"
                value={password}
                onChange={setPassword}
                autoComplete={mode === "signin" ? "current-password" : "new-password"}
              />
            )}

            {mode === "signin" && (
              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  onClick={() => setMode("forgot")}
                  className="text-xs font-medium text-foreground/60 hover:text-foreground"
                >
                  Forgot password?
                </button>
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-full bg-primary text-sm font-medium text-primary-foreground shadow-[0_10px_30px_-10px_hsl(var(--primary)/0.55)] transition-all hover:scale-[1.01] disabled:opacity-60"
            >
              {busy
                ? "Please wait…"
                : mode === "signin"
                ? "Sign in"
                : mode === "signup"
                ? "Create account"
                : "Send reset link"}
              {!busy && <ArrowRight className="h-4 w-4" />}
            </button>
          </form>

          {mode === "forgot" ? (
            <button
              type="button"
              onClick={() => setMode("signin")}
              className="mt-6 flex w-full items-center justify-center gap-1.5 text-xs font-medium text-foreground/60 hover:text-foreground"
            >
              <ArrowLeft className="h-3 w-3" /> Back to sign in
            </button>
          ) : (
            <p className="mt-6 text-center text-xs text-foreground/50">
              {mode === "signin" ? "New here?" : "Already have an account?"}{" "}
              <button
                type="button"
                onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
                className="font-medium text-foreground/80 underline-offset-2 hover:underline"
              >
                {mode === "signin" ? "Create an account" : "Sign in"}
              </button>
            </p>
          )}
        </div>
      </section>
    </main>
  );
};

const Field = ({
  icon,
  type,
  placeholder,
  value,
  onChange,
  autoComplete,
}: {
  icon: React.ReactNode;
  type: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
}) => (
  <label className="glass-chip flex h-12 items-center gap-3 rounded-2xl px-4 transition-all focus-within:ring-2 focus-within:ring-foreground/15">
    <span className="text-foreground/45">{icon}</span>
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      autoComplete={autoComplete}
      required
      className="flex-1 bg-transparent text-sm text-foreground placeholder:text-foreground/40 focus:outline-none"
    />
  </label>
);

export default Auth;
