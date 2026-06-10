import { ThemeToggle } from "../ui/ThemeToggle";
import { Button } from "../ui/Button";
import { Shield, ShieldAlert, LogOut, MessageSquare } from "lucide-react";
import { ClusterContextSelector } from "./ClusterContextSelector";
import { Breadcrumb } from "./Breadcrumb";
import { cn } from "../../lib/utils";
import { useChatContext } from "../../context/ChatContext";

interface HeaderProps {
  godModeActive: boolean;
  toggleGodMode: () => void;
  isSuperuser?: boolean;
  handleLogout: () => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean) => void;
}

export function Header({
  godModeActive, toggleGodMode, isSuperuser = false, handleLogout,
  sidebarCollapsed, setSidebarCollapsed,
}: HeaderProps) {
  const isGod = godModeActive;
  const { isStreaming, setPanelOpen } = useChatContext();

  return (
    <div className="flex items-center gap-2.5 w-full">
      {/* Sidebar toggle */}
      <button
        onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
        className="h-8 w-8 flex items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors flex-shrink-0"
        aria-label="Toggle sidebar"
      >
        <div className="flex flex-col justify-center gap-[3.5px] w-[14px]">
          <span className={cn(
            "block h-[1.5px] w-full bg-current rounded-full origin-center",
            "transition-transform duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
            !sidebarCollapsed ? "translate-y-[5px] rotate-45" : ""
          )} />
          <span className={cn(
            "block h-[1.5px] w-full bg-current rounded-full",
            "transition-all duration-200 ease-[cubic-bezier(0.4,0,0.2,1)]",
            !sidebarCollapsed ? "opacity-0 scale-x-0" : "opacity-100 scale-x-100"
          )} />
          <span className={cn(
            "block h-[1.5px] w-full bg-current rounded-full origin-center",
            "transition-transform duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
            !sidebarCollapsed ? "-translate-y-[5px] -rotate-45" : ""
          )} />
        </div>
      </button>

      {/* Breadcrumb */}
      <Breadcrumb />

      <div className="flex-1" />

      {/* Cluster selector */}
      <ClusterContextSelector />

      {/* AI streaming indicator — visible from any page */}
      {isStreaming && (
        <button
          onClick={() => {
            if (window.location.pathname === "/ai-chats") return;
            setPanelOpen(true);
          }}
          title="AI is responding — click to view"
          className="flex items-center gap-1.5 px-2.5 h-8 rounded-lg border border-cyan-500/30 bg-cyan-500/10 text-cyan-400 text-xs hover:bg-cyan-500/20 transition-colors"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse flex-shrink-0" />
          <MessageSquare className="w-3 h-3 flex-shrink-0" />
          <span className="font-mono hidden sm:inline">AI responding</span>
        </button>
      )}

      {/* God Mode tag */}
      {isGod && (
        <div className="flex items-center gap-1.5 bg-red-50 dark:bg-red-950/30 border border-red-200/80 dark:border-red-800/60 rounded-lg px-3 py-1 h-8">
          <div className="w-1.5 h-1.5 rounded-full bg-red-500 dot-pulse" />
          <span className="text-[11px] font-semibold font-mono text-red-600 dark:text-red-400 uppercase tracking-wider">
            GOD MODE
          </span>
        </div>
      )}

      {/* Mode toggle */}
      {isSuperuser && (
        <Button
          onClick={toggleGodMode}
          variant={isGod ? "destructive" : "outline"}
          size="sm"
          className="h-8 px-3 text-xs gap-1.5"
        >
          {isGod ? (
            <>
              <Shield className="w-3 h-3" />
              Normal Mode
            </>
          ) : (
            <>
              <ShieldAlert className="w-3 h-3" />
              God Mode
            </>
          )}
        </Button>
      )}

      <ThemeToggle />

      <button
        onClick={handleLogout}
        title="Logout"
        className="h-8 w-8 flex items-center justify-center rounded-lg text-muted-foreground hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
      >
        <LogOut className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
