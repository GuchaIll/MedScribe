import { Plus, Search, Calendar, LayoutGrid, LogOut, Settings as SettingsIcon } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { useProfile } from "@/hooks/useProfile";

const items = [
  { icon: Search, label: "Search", to: "/" },
  { icon: Calendar, label: "Schedule", to: "/schedule" },
  { icon: LayoutGrid, label: "Patient profile", to: "/patient" },
];

export const LeftRail = () => {
  const { pathname } = useLocation();
  const { user, signOut } = useAuth();
  const { profile } = useProfile();
  const navigate = useNavigate();

  const displayName = profile?.display_name ?? user?.email?.split("@")[0] ?? "Account";
  const initial = displayName[0]?.toUpperCase() ?? "?";

  const handleSignOut = async () => {
    await signOut();
    toast.success("Signed out");
    navigate("/auth", { replace: true });
  };

  return (
    <aside className="flex h-full w-[96px] flex-col items-center justify-between px-[25px] py-4 md:w-[118px] md:py-6">
      <div className="flex flex-col items-center gap-4">
        <Link
          to="/"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-[0_8px_24px_-8px_hsl(var(--primary)/0.4)] transition-transform hover:scale-105"
          aria-label="New session"
        >
          <Plus className="h-5 w-5" strokeWidth={2.2} />
        </Link>

        <nav className="mt-2 flex flex-col items-center gap-3">
          {items.map(({ icon: Icon, label, to }) => {
            const active = pathname === to;
            return (
              <Link
                key={label}
                to={to}
                aria-label={label}
                className={cn(
                  "glass-chip flex h-11 w-11 items-center justify-center rounded-full transition-all hover:scale-105",
                  active ? "text-foreground bg-white" : "text-foreground/70 hover:text-foreground"
                )}
              >
                <Icon className="h-[18px] w-[18px]" strokeWidth={1.8} />
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="flex flex-col items-center gap-3">
        <Link
          to="/settings"
          aria-label={`Profile settings — ${displayName}`}
          title={displayName}
          className={cn(
            "group relative flex h-11 w-11 items-center justify-center overflow-hidden rounded-full transition-all hover:scale-105",
            pathname === "/settings"
              ? "ring-2 ring-foreground/20"
              : ""
          )}
        >
          {profile?.avatar_url ? (
            <img
              src={profile.avatar_url}
              alt={displayName}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="glass-chip flex h-full w-full items-center justify-center rounded-full text-[13px] font-semibold text-foreground/80">
              {initial}
            </span>
          )}
        </Link>
        <span className="max-w-[68px] truncate text-center text-[10.5px] font-medium text-foreground/70">
          {displayName}
        </span>
        <Link
          to="/settings"
          aria-label="Settings"
          className="glass-chip flex h-9 w-9 items-center justify-center rounded-full text-foreground/60 transition-all hover:scale-105 hover:text-foreground"
        >
          <SettingsIcon className="h-[15px] w-[15px]" strokeWidth={1.8} />
        </Link>
        <button
          onClick={handleSignOut}
          aria-label="Sign out"
          className="glass-chip flex h-9 w-9 items-center justify-center rounded-full text-foreground/60 transition-all hover:scale-105 hover:text-foreground"
        >
          <LogOut className="h-[15px] w-[15px]" strokeWidth={1.8} />
        </button>
      </div>
    </aside>
  );
};
