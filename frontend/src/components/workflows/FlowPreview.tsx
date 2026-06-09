import { Globe, Mail, Sparkles, Zap } from "lucide-react";
import type { WorkflowStep } from "../../types/workflow";

import jenkinsLogo  from "../../assets/logos/jenkins.svg";
import slackLogo    from "../../assets/logos/slack.svg";
import k8sLogo      from "../../assets/logos/kubernetes.svg";
import jiraLogo     from "../../assets/logos/jira.svg";
import argocdLogo   from "../../assets/logos/argocd.svg";
import teamsLogo    from "../../assets/logos/teams.svg";

const CONNECTOR_ICONS: Record<string, React.ReactNode> = {
  http:       <Globe size={13} className="text-sky-400" />,
  jenkins:    <img src={jenkinsLogo}  alt="Jenkins"    className="w-4 h-4 object-contain" />,
  argocd:     <img src={argocdLogo}   alt="ArgoCD"     className="w-4 h-4 object-contain" />,
  k8s:        <img src={k8sLogo}      alt="Kubernetes"  className="w-4 h-4 object-contain" />,
  slack:      <img src={slackLogo}    alt="Slack"       className="w-4 h-4 object-contain" />,
  teams:      <img src={teamsLogo}    alt="Teams"       className="w-4 h-4 object-contain" />,
  jira:       <img src={jiraLogo}     alt="Jira"        className="w-4 h-4 object-contain" />,
  email:      <Mail size={13} className="text-muted-foreground" />,
  ai_analyze: <Sparkles size={13} className="text-primary" />,
};

interface Props {
  steps: WorkflowStep[];
}

export function FlowPreview({ steps }: Props) {
  return (
    <div className="flex flex-col items-center gap-0 py-2">
      <div className="flex flex-col items-center">
        <div className="bg-primary/15 border border-primary rounded-lg px-4 py-2 text-primary text-xs font-medium flex items-center gap-1.5">
          <Zap size={11} />
          Trigger
        </div>
        {steps.length > 0 && <div className="w-px h-4 bg-border" />}
      </div>

      {steps.map((step, i) => (
        <div key={step.id} className="flex flex-col items-center">
          <div className="bg-card border border-border rounded-lg px-3 py-2 text-card-foreground flex items-center gap-2 max-w-[180px]">
            <div className="flex-shrink-0 flex items-center justify-center w-4 h-4">
              {CONNECTOR_ICONS[step.connector_type] ?? <Globe size={13} className="text-muted-foreground" />}
            </div>
            <span className="truncate text-xs">{step.name || step.connector_type}</span>
          </div>
          {i < steps.length - 1 && <div className="w-px h-4 bg-border" />}
        </div>
      ))}

      {steps.length === 0 && (
        <div className="text-muted-foreground text-xs mt-4">Add steps to preview flow</div>
      )}
    </div>
  );
}
