import { useLocation } from "react-router-dom";

const ROUTE_LABELS: Record<string, string> = {
  dashboard:      "dashboard",
  resources:      "resources",
  toolsets:       "toolsets",
  audit:          "audit",
  settings:       "settings",
  admin:          "admin",
  info:           "info",
  docs:           "docs",
  runbooks:       "runbooks",
  "ai-chats":     "ai-chats",
  "mcp-servers":  "mcp-servers",
  integrations:   "integrations",
  "knowledge-base": "knowledge-base",
};

export function Breadcrumb() {
  const { pathname } = useLocation();
  const segment = pathname.split("/").filter(Boolean)[0] ?? "";
  const label = ROUTE_LABELS[segment] ?? segment;

  return (
    <nav className="flex items-center gap-1 text-xs font-mono" aria-label="breadcrumb">
      <span className="text-primary/50 select-none">~/</span>
      <span className="text-muted-foreground/50">dokops</span>
      <span className="text-muted-foreground/30 mx-0.5">/</span>
      <span className="text-foreground/80 font-medium">{label}</span>
    </nav>
  );
}
