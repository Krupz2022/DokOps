import React, { useState } from "react";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { Footer } from "./Footer";
import { GodModeBanner } from "./GodModeBanner";
import { useAppContext } from "../../context/AppContext";
import { useConfirm } from "../../context/ConfirmContext";
import { cn } from "../../lib/utils";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const { godModeActive, toggleGodMode, isSuperuser } = useAppContext();
  const { confirm } = useConfirm();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const handleToggleMode = async () => {
    if (!godModeActive) {
      const ok = await confirm({
        title: "Enable God Mode",
        description: "Grants full permissions including DELETE on all cluster resources. Use with caution in production environments.",
        variant: "warning",
        confirmLabel: "Enable God Mode",
        cancelLabel: "Stay Safe",
      });
      if (!ok) return;
    }
    await toggleGodMode();
  };

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    window.location.href = "/login";
  };

  return (
    <div className="h-screen overflow-hidden bg-background flex">
      <Sidebar collapsed={sidebarCollapsed} setCollapsed={setSidebarCollapsed} />

      <div
        className={cn(
          "flex-1 flex flex-col h-full transition-[margin-left] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
          sidebarCollapsed ? "ml-14" : "ml-56"
        )}
      >
        {/* Glass top header */}
        <header className={cn(
          "sticky top-0 z-30 border-b border-border h-14 flex items-center px-4 flex-shrink-0",
          "glass-header"
        )}>
          <Header
            godModeActive={godModeActive}
            toggleGodMode={handleToggleMode}
            isSuperuser={isSuperuser}
            handleLogout={handleLogout}
            sidebarCollapsed={sidebarCollapsed}
            setSidebarCollapsed={setSidebarCollapsed}
          />
        </header>

        {/* God Mode banner */}
        <GodModeBanner visible={godModeActive} />

        {/* Page content */}
        <main className="flex-1 min-h-0 overflow-y-auto flex flex-col">
          {children}
        </main>

        <Footer />
      </div>
    </div>
  );
}
