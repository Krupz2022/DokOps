import { X, Globe, Mail, Sparkles } from "lucide-react";

import jenkinsLogo  from "../../assets/logos/jenkins.svg";
import slackLogo    from "../../assets/logos/slack.svg";
import k8sLogo      from "../../assets/logos/kubernetes.svg";
import jiraLogo     from "../../assets/logos/jira.svg";
import argocdLogo   from "../../assets/logos/argocd.svg";
import teamsLogo    from "../../assets/logos/teams.svg";

type ConnectorType = "http" | "jenkins" | "argocd" | "k8s" | "slack" | "teams" | "jira" | "email" | "ai_analyze";

interface ConnectorMeta {
  label: string;
  description: string;
  icon: React.ReactNode;
}

const ImgIcon = ({ src, alt }: { src: string; alt: string }) => (
  <img src={src} alt={alt} className="w-7 h-7 object-contain" />
);

const CONNECTORS: Record<ConnectorType, ConnectorMeta> = {
  http:       { label: "HTTP Request",    description: "Call any REST API",               icon: <Globe className="w-7 h-7 text-sky-400" /> },
  jenkins:    { label: "Jenkins",         description: "Build status, logs, trigger",     icon: <ImgIcon src={jenkinsLogo}  alt="Jenkins" /> },
  argocd:     { label: "ArgoCD",          description: "App status, sync",                icon: <ImgIcon src={argocdLogo}   alt="ArgoCD" /> },
  k8s:        { label: "Kubernetes",      description: "Pod logs, events, status",        icon: <ImgIcon src={k8sLogo}      alt="Kubernetes" /> },
  slack:      { label: "Slack",           description: "Post message to channel",         icon: <ImgIcon src={slackLogo}    alt="Slack" /> },
  teams:      { label: "Microsoft Teams", description: "Post message or card",            icon: <ImgIcon src={teamsLogo}    alt="Teams" /> },
  jira:       { label: "Jira",            description: "Create issue, add comment",       icon: <ImgIcon src={jiraLogo}     alt="Jira" /> },
  email:      { label: "Email",           description: "Send email via SMTP",             icon: <Mail className="w-7 h-7 text-muted-foreground" /> },
  ai_analyze: { label: "AI Analyze",      description: "Reason over all collected data",  icon: <Sparkles className="w-7 h-7 text-primary" /> },
};

const CONNECTOR_ORDER: ConnectorType[] = [
  "http", "jenkins", "argocd", "k8s", "slack", "teams", "jira", "email", "ai_analyze",
];

interface Props {
  onSelect: (type: string) => void;
  onClose: () => void;
}

export function ConnectorPicker({ onSelect, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-xl w-full max-w-lg p-6 shadow-glow">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-foreground font-semibold text-lg">Choose Connector</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <X size={20} />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {CONNECTOR_ORDER.map((type) => {
            const c = CONNECTORS[type];
            return (
              <button
                key={type}
                onClick={() => onSelect(type)}
                className="flex items-center gap-3 p-3 rounded-lg bg-background hover:bg-muted border border-border hover:border-primary text-left transition-colors"
              >
                <div className="w-8 h-8 flex items-center justify-center flex-shrink-0">
                  {c.icon}
                </div>
                <div>
                  <div className="text-foreground text-sm font-medium">{c.label}</div>
                  <div className="text-muted-foreground text-xs">{c.description}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
