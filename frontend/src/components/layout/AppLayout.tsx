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

  return (
    <div className="h-screen overflow-hidden bg-background flex">
      <Sidebar collapsed={sidebarCollapsed} setCollapsed={setSidebarCollapsed} />

      {/* min-w-0: without it this flex item keeps min-width:auto and cannot shrink
          below its widest child, so one wide element (a log <pre>, a table) pushes
          the column past the viewport — and the parent's overflow-hidden clips it
          rather than scrolling. */}
      <div
        className={cn(
          "flex-1 min-w-0 flex flex-col h-full transition-[margin-left] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
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
            sidebarCollapsed={sidebarCollapsed}
            setSidebarCollapsed={setSidebarCollapsed}
          />
        </header>

        {/* God Mode banner */}
        <GodModeBanner visible={godModeActive} />

        {/* Page content */}
        <main className="flex-1 min-h-0 min-w-0 overflow-y-auto flex flex-col">
          {children}
        </main>

        <Footer />
      </div>
    </div>
  );
}
