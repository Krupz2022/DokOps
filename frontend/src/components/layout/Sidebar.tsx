import React, { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Box, Wrench, FileText, Settings, BookOpen,
  ShieldAlert, MessageSquare, Database, Plug, Network, Orbit, GitBranch, Workflow, Server,
  Building2, ShieldCheck, ArrowRightCircle, Clock, BellDot, Vault, LogOut, BarChart2,
  ExternalLink, Sun, Moon, ScrollText, Boxes, ChevronDown, ChevronRight,
} from "lucide-react";
import { useTheme } from "../ui/ThemeProvider";
import { cn } from "../../lib/utils";
import api from "../../lib/api";
import { useAppContext } from "../../context/AppContext";

interface SidebarProps {
  collapsed: boolean;
  setCollapsed: (c: boolean) => void;
}

interface NavItem {
  name: string;
  path: string;
  icon: React.ElementType;
}

interface NavSection {
  label: string;
  items: NavItem[];
  collapsible?: boolean;
  icon?: React.ElementType;
}

function useNavSections(ragEnabled: boolean): NavSection[] {
  return [
    {
      label: "MAIN",
      items: [
        { name: "Dashboard",    path: "/dashboard",    icon: LayoutDashboard },
        { name: "Resources",    path: "/resources",    icon: Box },
        { name: "Topology",     path: "/topology",     icon: GitBranch },
        { name: "Runbooks",     path: "/runbooks",     icon: BookOpen },
        { name: "AI Chats",     path: "/ai-chats",     icon: MessageSquare },
        { name: "Workflows",    path: "/workflows",    icon: Workflow },
        { name: "Alert Incidents", path: "/alerts", icon: BellDot },
        ...(ragEnabled ? [{ name: "Knowledge Base", path: "/knowledge-base", icon: Database }] : []),
        { name: "Knowledge Sources", path: "/knowledge-sources", icon: ExternalLink },
      ],
    },
    {
      label: "INFRASTRUCTURE",
      items: [
        { name: "Clusters",       path: "/clusters",                        icon: Orbit },
        { name: "Vault",          path: "/vault",                           icon: Vault },
      ],
    },
    {
      label: "Fleet",
      collapsible: true,
      icon: Boxes,
      items: [
        { name: "Minions",        path: "/infrastructure/minions",          icon: Server },
        { name: "Blueprints",     path: "/infrastructure/blueprints",       icon: ScrollText },
        { name: "Groups",         path: "/infrastructure/organisations",    icon: Building2 },
        { name: "Compliance",     path: "/patching",                        icon: ShieldCheck },
        { name: "Pipelines",      path: "/patching/pipelines",              icon: ArrowRightCircle },
        { name: "Schedules",      path: "/patching/schedules",              icon: Clock },
      ],
    },
    {
      label: "CONFIG",
      items: [
        { name: "Toolsets",     path: "/toolsets",     icon: Wrench },
        { name: "MCP Servers",  path: "/mcp-servers",  icon: Network },
        { name: "Integrations", path: "/integrations", icon: Plug },
      ],
    },
  ];
}

export function Sidebar({ collapsed, setCollapsed }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { isSuperuser } = useAppContext();
  const { theme, setTheme } = useTheme();
  const [ragEnabled, setRagEnabled] = useState(false);
  const [popupOpen, setPopupOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ Fleet: true });
  const popupRef = useRef<HTMLDivElement>(null);

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  useEffect(() => {
    api.get("/ai/config")
      .then((res) => {
        setRagEnabled((res.data as Record<string, string>).rag_enabled === "true");
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!popupOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        setPopupOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [popupOpen]);

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    window.location.href = "/login";
  };

  const allSections = useNavSections(ragEnabled);
  const navSections = allSections.map(section => ({
    ...section,
    items: section.items.filter(item => item.path !== "/admin" || isSuperuser),
  }));

  const userStr = localStorage.getItem("user");
  const user = userStr ? JSON.parse(userStr) : null;
  const initials = user?.username ? user.username.slice(0, 2).toUpperCase() : "U";

  // nested = item lives inside a collapsible group → indent it under the group header
  const renderNavItem = (item: NavItem, nested: boolean) => {
    const isActive = location.pathname === item.path;
    return (
      <Link
        key={item.path}
        to={item.path}
        onClick={() => {
          if (window.innerWidth < 1024) setCollapsed(true);
        }}
        className={cn(
          "w-full flex items-center transition-all duration-150 group relative text-sm",
          collapsed ? "px-0 py-2.5 justify-center" : nested ? "pl-9 pr-4 py-2" : "px-4 py-2",
          isActive
            ? cn(
                "nav-active-gradient text-foreground border-l-2 border-primary dark:shadow-glow-sm",
                collapsed ? "" : nested ? "pl-[calc(2.25rem-2px)]" : "pl-[calc(1rem-2px)]"
              )
            : "text-muted-foreground hover:text-foreground hover:bg-secondary/40 border-l-2 border-transparent"
        )}
      >
        <item.icon
          className={cn(
            "flex-shrink-0 transition-colors duration-150",
            collapsed ? "w-4 h-4" : "w-3.5 h-3.5 mr-2.5",
            isActive
              ? "text-primary drop-shadow-[0_0_6px_hsl(191_89%_55%_/_0.6)]"
              : "text-muted-foreground group-hover:text-foreground"
          )}
        />
        {!collapsed && (
          <span className={cn("truncate sidebar-text-in", isActive ? "font-medium" : "font-normal")}>
            {item.name}
          </span>
        )}

        {/* Active indicator dot */}
        {isActive && collapsed && (
          <span className="absolute right-1 top-1/2 -translate-y-1/2 w-1 h-1 rounded-full bg-primary shadow-[0_0_6px_hsl(191_89%_55%_/_0.8)]" />
        )}

        {/* Collapsed tooltip */}
        {collapsed && (
          <span className="absolute left-full ml-2 px-2.5 py-1.5 glass border border-border text-foreground text-xs rounded-md opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 shadow-lg font-medium">
            {item.name}
          </span>
        )}
      </Link>
    );
  };

  return (
    <>
      {!collapsed && (
        <div
          className="fixed inset-0 bg-black/60 z-30 lg:hidden backdrop-blur-sm"
          onClick={() => setCollapsed(true)}
        />
      )}

      <aside
        className={cn(
          "h-screen flex flex-col fixed left-0 top-0 z-40 overflow-hidden scanline",
          "glass-sidebar border-r border-border",
          "transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] dark:shadow-glow",
          collapsed ? "w-14" : "w-56"
        )}
      >
        {/* Logo */}
        <div className={cn(
          "flex items-center h-14 border-b border-border flex-shrink-0",
          "dark:border-b dark:[border-bottom-color:hsl(191_89%_55%_/_0.08)]",
          collapsed ? "px-3 justify-center" : "px-4 gap-3"
        )}>
          <div className={cn(
            "w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0",
            "bg-gradient-to-br from-cyan-400 to-sky-600",
            "shadow-lg shadow-cyan-500/30 logo-glow"
          )}>
            <Orbit className="w-4 h-4 text-white" strokeWidth={2} />
          </div>
          {!collapsed && (
            <div className="min-w-0 sidebar-text-in">
              <p className="font-semibold text-foreground text-sm leading-none tracking-tight">DokOps</p>
              <p className="text-[10px] text-muted-foreground font-mono mt-0.5 leading-none opacity-50 tracking-widest uppercase">
                k8s platform
              </p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 overflow-y-auto">
          {navSections.map((section) => {
            // Collapsible groups (e.g. Fleet) only fold when the rail is expanded.
            const isGroup = !!section.collapsible && !collapsed;
            const open = openGroups[section.label] ?? true;
            return (
              <div key={section.label} className="mb-5">
                {!collapsed && (
                  isGroup ? (
                    <button
                      onClick={() => setOpenGroups((g) => ({ ...g, [section.label]: !open }))}
                      className="w-full flex items-center gap-2 px-4 mb-1 text-muted-foreground hover:text-foreground transition-colors group/section"
                    >
                      {section.icon && <section.icon className="w-3.5 h-3.5 flex-shrink-0" />}
                      <span className="text-[11px] font-semibold tracking-wide flex-1 text-left sidebar-text-in">
                        {section.label}
                      </span>
                      {open
                        ? <ChevronDown className="w-3.5 h-3.5 opacity-50 group-hover/section:opacity-100" />
                        : <ChevronRight className="w-3.5 h-3.5 opacity-50 group-hover/section:opacity-100" />}
                    </button>
                  ) : (
                    <p className="px-4 mb-1.5 text-[9px] font-mono font-semibold text-muted-foreground/35 tracking-[0.2em] sidebar-text-in">
                      {section.label}
                    </p>
                  )
                )}
                {(!isGroup || open) && section.items.map((item) => renderNavItem(item, isGroup))}
              </div>
            );
          })}
        </nav>

        {/* User row + popup */}
        <div ref={popupRef} className="flex-shrink-0 border-t border-border relative dark:[border-top-color:hsl(191_89%_55%_/_0.08)]">
          {/* Popup */}
          {popupOpen && (
            <div className={cn(
              "absolute bottom-full mb-1.5 z-50",
              "glass border border-border rounded-xl shadow-xl overflow-hidden",
              collapsed ? "left-1/2 -translate-x-1/2 w-44" : "left-3 right-3"
            )}>
              {/* User info header */}
              <div className="px-3.5 py-2.5 border-b border-border/60 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-foreground truncate">{user?.username ?? "User"}</p>
                  <p className="text-[10px] text-muted-foreground font-mono truncate opacity-60">{user?.role ?? "user"}</p>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); toggleTheme(); }}
                  className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
                  title="Toggle theme"
                >
                  {theme === "dark"
                    ? <Sun className="w-3.5 h-3.5" />
                    : <Moon className="w-3.5 h-3.5" />}
                </button>
              </div>

              {/* Menu items */}
              <div className="py-1">
                <button
                  onClick={() => { navigate("/settings"); setPopupOpen(false); }}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
                >
                  <Settings className="w-3.5 h-3.5 flex-shrink-0" />
                  Settings
                </button>
                <button
                  onClick={() => { navigate("/audit"); setPopupOpen(false); }}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
                >
                  <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                  Audit Logs
                </button>
                {isSuperuser && (
                  <>
                    <button
                      onClick={() => { navigate("/admin"); setPopupOpen(false); }}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
                    >
                      <ShieldAlert className="w-3.5 h-3.5 flex-shrink-0" />
                      Admin Panel
                    </button>
                    <button
                      onClick={() => { navigate("/analytics"); setPopupOpen(false); }}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
                    >
                      <BarChart2 className="w-3.5 h-3.5 flex-shrink-0" />
                      Analytics
                    </button>
                  </>
                )}
              </div>

              <div className="border-t border-border/60 py-1">
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5 flex-shrink-0" />
                  Sign Out
                </button>
              </div>
            </div>
          )}

          <div
            onClick={() => setPopupOpen((v) => !v)}
            className={cn(
              "flex items-center h-10 transition-colors cursor-pointer hover:bg-secondary/30",
              popupOpen && "bg-secondary/40",
              collapsed ? "px-3 justify-center" : "px-4 gap-2.5"
            )}
          >
            <div className="relative flex-shrink-0">
              <div className={cn(
                "w-7 h-7 rounded-lg flex items-center justify-center",
                "bg-gradient-to-br from-cyan-400 to-sky-600",
                "shadow-sm shadow-cyan-500/30"
              )}>
                <span className="text-white text-[10px] font-bold">{initials}</span>
              </div>
              <div className="absolute -bottom-0.5 -right-0.5 w-2 h-2 bg-emerald-400 rounded-full border-[1.5px] border-sidebar dot-pulse shadow-[0_0_6px_#4ade8080]" />
            </div>
            {!collapsed && (
              <div className="flex flex-col min-w-0 sidebar-text-in flex-1">
                <span className="text-xs font-medium text-foreground truncate leading-snug">
                  {user?.username ?? "User"}
                </span>
                <span className="text-[10px] text-muted-foreground truncate font-mono leading-none opacity-50 tracking-wider">
                  {user?.role ?? "user"}
                </span>
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
