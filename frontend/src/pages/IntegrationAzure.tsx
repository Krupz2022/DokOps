import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Cloud, CheckCircle2, RefreshCw, Loader2, Unplug, ChevronDown, ChevronUp, DollarSign, Server, Activity, Sparkles } from "lucide-react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { AzureFeatureCard } from "../components/integrations/AzureFeatureCard";

interface FeatureState {
  enabled: boolean;
  last_synced_at: string | null;
}

interface AzureStatus {
  connected: boolean;
  tenant_id: string | null;
  subscription_id: string | null;
  resource_group: string | null;
  aks_cluster_name: string | null;
  connected_at: string | null;
  features: Record<string, FeatureState>;
}

interface AzureAnalysisItem {
  name?: string;
  type?: string;
  reason?: string;
  issue?: string;
  title?: string;
  detail?: string;
}

interface AzureAnalysis {
  summary: string;
  orphaned: AzureAnalysisItem[];
  anomalies: AzureAnalysisItem[];
  recommendations: AzureAnalysisItem[];
}

const FEATURES = [
  {
    key: "cost_optimization",
    title: "Cost Optimization",
    description: "Pull 30-day billing data for your resource group and all resources within it.",
    incursCost: false,
  },
  {
    key: "resource_discovery",
    title: "Resource Discovery",
    description: "List all resources in your RG and scan the subscription for related resources via Azure Resource Graph.",
    incursCost: false,
  },
  {
    key: "azure_monitor",
    title: "Azure Monitor",
    description: "Fetch standard AKS platform metrics (CPU, memory, node utilization) from Azure Monitor.",
    incursCost: true,
    costWarning:
      "Standard platform metrics are free. If your cluster has Container Insights / Log Analytics enabled, querying logs may incur charges based on data volume.",
  },
  {
    key: "cost_anomaly_alerting",
    title: "Cost Anomaly Alerting",
    description: "Surface Azure Cost Management anomaly alerts for your resource group.",
    incursCost: false,
  },
  {
    key: "ai_cost_recommendations",
    title: "AI Cost Recommendations",
    description: "Enable the AI to call Azure Advisor cost recommendations during chat. Advisor results are also shown here.",
    incursCost: false,
  },
];

export default function IntegrationAzure() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [status, setStatus] = useState<AzureStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [testingConnection, setTestingConnection] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false);

  const [anomaliesData, setAnomaliesData] = useState<any>(null);
  const [recommendationsData, setRecommendationsData] = useState<any>(null);
  const [costData, setCostData] = useState<any>(null);
  const [resourcesData, setResourcesData] = useState<any>(null);
  const [monitorData, setMonitorData] = useState<any>(null);
  const [analysisData, setAnalysisData] = useState<AzureAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [expandedPanels, setExpandedPanels] = useState<Record<string, boolean>>({});

  useEffect(() => {
    fetchStatus();
  }, []);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const res = await api.get("/integrations/azure/status");
      setStatus(res.data);
      const f = res.data.features ?? {};
      if (f.cost_optimization?.enabled) fetchCostData();
      if (f.resource_discovery?.enabled) fetchResourcesData();
      if (f.azure_monitor?.enabled) fetchMonitorData();
      if (f.cost_anomaly_alerting?.enabled) fetchAnomalies();
      if (f.ai_cost_recommendations?.enabled) fetchRecommendations();
    } catch {
      navigate("/integrations");
    } finally {
      setLoading(false);
    }
  };

  const fetchCostData = async () => {
    try { setCostData((await api.get("/integrations/azure/cost")).data); } catch {}
  };
  const fetchResourcesData = async () => {
    try { setResourcesData((await api.get("/integrations/azure/resources")).data); } catch {}
  };
  const fetchMonitorData = async () => {
    try { setMonitorData((await api.get("/integrations/azure/monitor")).data); } catch {}
  };

  const runAnalysis = async () => {
    setAnalysisLoading(true);
    setAnalysisError(null);
    try {
      const res = await api.post("/integrations/azure/analyze-resources");
      setAnalysisData(res.data);
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setAnalysisError(typeof detail === "string" ? detail : "Analysis failed. Try again.");
    } finally {
      setAnalysisLoading(false);
    }
  };
  const buildDeepDivePrompt = () => {
    if (!resourcesData) return "";
    const lines = [
      ...(resourcesData.direct_resources ?? []),
      ...(resourcesData.linked_resources ?? []),
    ]
      .map((r: any) => `- ${r.name} (${r.type?.split("/").slice(-1)[0]}, ${r.location})`)
      .join("\n");
    return `I have the following Azure resources:\n${lines}\n\nPlease help me analyse them in detail — identify orphaned resources, cost waste, regional mismatches, and give me actionable recommendations.`;
  };

  const fetchAnomalies = async () => {
    try { setAnomaliesData((await api.get("/integrations/azure/anomalies")).data); } catch {}
  };
  const fetchRecommendations = async () => {
    try { setRecommendationsData((await api.get("/integrations/azure/recommendations")).data); } catch {}
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    try {
      await api.post("/integrations/azure/test");
      toast("Connection test passed", "success");
      fetchStatus();
    } catch {
      toast("Connection test failed", "error");
    } finally {
      setTestingConnection(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await api.delete("/integrations/azure/disconnect");
      toast("Azure disconnected", "success");
      navigate("/integrations");
    } catch {
      toast("Failed to disconnect", "error");
    } finally {
      setDisconnecting(false);
      setShowDisconnectConfirm(false);
    }
  };

  const handleToggleFeature = async (key: string, enabled: boolean) => {
    await api.patch(`/integrations/azure/features/${key}`, { enabled });
    toast(`${enabled ? "Enabled" : "Disabled"} successfully`, "success");
    await fetchStatus();
    if (enabled) {
      if (key === "cost_optimization") fetchCostData();
      if (key === "resource_discovery") fetchResourcesData();
      if (key === "azure_monitor") fetchMonitorData();
      if (key === "cost_anomaly_alerting") fetchAnomalies();
      if (key === "ai_cost_recommendations") fetchRecommendations();
    }
  };

  const togglePanel = (key: string) => {
    setExpandedPanels((p) => ({ ...p, [key]: !p[key] }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 px-6 py-4">
        <button
          onClick={() => navigate("/integrations")}
          className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 dark:text-muted-foreground dark:hover:text-foreground transition-colors mb-3"
        >
          <ArrowLeft className="h-4 w-4" />
          Integrations
        </button>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-950/30 flex items-center justify-center">
              <Cloud className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900 dark:text-foreground">Azure Integration</h1>
              {status?.tenant_id && (
                <p className="text-xs text-slate-500 dark:text-muted-foreground">
                  Tenant: {status.tenant_id}
                </p>
              )}
            </div>
            {status?.connected && (
              <div className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400 font-medium">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Connected
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleTestConnection}
              disabled={testingConnection}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-border text-slate-600 dark:text-muted-foreground hover:bg-slate-50 dark:hover:bg-accent transition-colors disabled:opacity-50"
            >
              {testingConnection ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Test Connection
            </button>
            <button
              onClick={() => setShowDisconnectConfirm(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-red-200 dark:border-red-800/50 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20 transition-colors"
            >
              <Unplug className="h-3.5 w-3.5" />
              Disconnect
            </button>
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
      <div className="space-y-6">
      {/* Feature cards */}
      <div>
        <h2 className="text-sm font-semibold text-slate-700 dark:text-foreground mb-3">Features</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f) => (
            <AzureFeatureCard
              key={f.key}
              featureKey={f.key}
              title={f.title}
              description={f.description}
              enabled={status?.features?.[f.key]?.enabled ?? false}
              lastSyncedAt={status?.features?.[f.key]?.last_synced_at}
              incursCost={f.incursCost}
              costWarning={f.costWarning}
              onToggle={handleToggleFeature}
            />
          ))}
        </div>
      </div>

      {/* Data panels */}
      <div className="space-y-3">
        {status?.features?.cost_optimization?.enabled && costData && (
          <DataPanel
            title={`Cost Optimization — ${costData.rows?.length ?? 0} resources (month-to-date)`}
            icon={<DollarSign className="h-4 w-4 text-green-500" />}
            expanded={expandedPanels["cost"]}
            onToggle={() => togglePanel("cost")}
          >
            {!costData.rows?.length ? (
              <p className="text-sm text-slate-500 dark:text-muted-foreground">No cost data found for this resource group.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-slate-400 dark:text-muted-foreground border-b border-slate-100 dark:border-border">
                      <th className="pb-2 font-medium">Resource</th>
                      <th className="pb-2 font-medium text-right">Cost (USD)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50 dark:divide-border">
                    {[...costData.rows]
                      .sort((a: any, b: any) => (b.Cost ?? 0) - (a.Cost ?? 0))
                      .map((row: any, i: number) => {
                        const resourceName = row.ResourceId?.split("/").pop() ?? row.ResourceId ?? "—";
                        return (
                          <tr key={i} className="text-slate-700 dark:text-foreground">
                            <td className="py-1.5 pr-4 max-w-xs truncate" title={row.ResourceId}>{resourceName}</td>
                            <td className="py-1.5 text-right font-mono">{typeof row.Cost === "number" ? `$${row.Cost.toFixed(2)}` : "—"}</td>
                          </tr>
                        );
                      })}
                  </tbody>
                  <tfoot>
                    <tr className="text-slate-600 dark:text-muted-foreground border-t border-slate-200 dark:border-border font-medium">
                      <td className="pt-2">Total</td>
                      <td className="pt-2 text-right font-mono">
                        ${costData.rows.reduce((sum: number, r: any) => sum + (r.Cost ?? 0), 0).toFixed(2)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </DataPanel>
        )}

        {status?.features?.resource_discovery?.enabled && resourcesData && (
          <DataPanel
            title={`Resource Discovery — ${resourcesData.total_direct ?? 0} direct, ${resourcesData.total_linked ?? 0} linked`}
            icon={<Server className="h-4 w-4 text-blue-500" />}
            expanded={expandedPanels["resources"]}
            onToggle={() => togglePanel("resources")}
          >
            <div className="space-y-4">
              {resourcesData.direct_resources?.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 dark:text-muted-foreground mb-2 uppercase tracking-wide">
                    In {resourcesData.resource_group}
                  </p>
                  <ul className="space-y-1">
                    {resourcesData.direct_resources.map((r: any, i: number) => (
                      <li key={i} className="flex items-center justify-between text-xs bg-slate-50 dark:bg-muted rounded-lg px-3 py-2">
                        <span className="font-medium text-slate-700 dark:text-foreground">{r.name}</span>
                        <span className="text-slate-400 dark:text-muted-foreground ml-4 truncate max-w-[40%] text-right">{r.type?.split("/").slice(-1)[0]}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {resourcesData.linked_resources?.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 dark:text-muted-foreground mb-2 uppercase tracking-wide">
                    Linked (subscription-wide match)
                  </p>
                  <ul className="space-y-1">
                    {resourcesData.linked_resources.map((r: any, i: number) => (
                      <li key={i} className="flex items-center justify-between text-xs bg-slate-50 dark:bg-muted rounded-lg px-3 py-2">
                        <div>
                          <span className="font-medium text-slate-700 dark:text-foreground">{r.name}</span>
                          <span className="ml-2 text-slate-400 dark:text-muted-foreground">{r.resource_group}</span>
                        </div>
                        <span className="text-slate-400 dark:text-muted-foreground ml-4 truncate max-w-[40%] text-right">{r.type?.split("/").slice(-1)[0]}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {!resourcesData.direct_resources?.length && !resourcesData.linked_resources?.length && (
                <p className="text-sm text-slate-500 dark:text-muted-foreground">No resources found.</p>
              )}

              {/* AI Analysis */}
              <div className="mt-4 pt-4 border-t border-slate-100 dark:border-border">
                {!analysisData ? (
                  <button
                    onClick={runAnalysis}
                    disabled={analysisLoading}
                    className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors disabled:opacity-50"
                  >
                    {analysisLoading ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Sparkles className="h-3 w-3" />
                    )}
                    {analysisLoading ? "Analysing..." : "Analyse with AI"}
                  </button>
                ) : (
                  <button
                    onClick={runAnalysis}
                    disabled={analysisLoading}
                    className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-border text-slate-600 dark:text-muted-foreground hover:bg-slate-50 dark:hover:bg-accent transition-colors disabled:opacity-50"
                  >
                    {analysisLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                    Re-analyse
                  </button>
                )}

                {analysisError && (
                  <p className="mt-2 text-xs text-red-500 dark:text-red-400">{analysisError}</p>
                )}

                {analysisData && !analysisLoading && (
                  <div className="mt-3 rounded-xl border border-slate-200 dark:border-border bg-white dark:bg-card p-4 space-y-4">
                    <p className="text-xs text-slate-500 dark:text-muted-foreground italic leading-relaxed">
                      {analysisData.summary}
                    </p>

                    {analysisData.orphaned.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-red-600 dark:text-red-400 mb-2 uppercase tracking-wide">
                          Orphaned Resources ({analysisData.orphaned.length})
                        </p>
                        <ul className="space-y-1">
                          {analysisData.orphaned.map((item, i) => (
                            <li key={i} className="text-xs bg-red-50 dark:bg-red-950/20 border border-red-100 dark:border-red-900/30 rounded-lg px-3 py-2">
                              <span className="font-medium text-red-700 dark:text-red-300">{item.name}</span>
                              <span className="text-red-500 dark:text-red-400 ml-2">— {item.reason}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {analysisData.anomalies.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-amber-600 dark:text-amber-400 mb-2 uppercase tracking-wide">
                          Anomalies ({analysisData.anomalies.length})
                        </p>
                        <ul className="space-y-1">
                          {analysisData.anomalies.map((item, i) => (
                            <li key={i} className="text-xs bg-amber-50 dark:bg-amber-950/20 border border-amber-100 dark:border-amber-900/30 rounded-lg px-3 py-2">
                              <span className="font-medium text-amber-700 dark:text-amber-300">{item.name}</span>
                              <span className="text-amber-500 dark:text-amber-400 ml-2">— {item.issue}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {analysisData.recommendations.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-blue-600 dark:text-blue-400 mb-2 uppercase tracking-wide">
                          Recommendations ({analysisData.recommendations.length})
                        </p>
                        <ul className="space-y-1">
                          {analysisData.recommendations.map((item, i) => (
                            <li key={i} className="text-xs bg-blue-50 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/30 rounded-lg px-3 py-2">
                              <span className="font-medium text-blue-700 dark:text-blue-300">{item.title}</span>
                              <span className="text-blue-500 dark:text-blue-400 ml-2">— {item.detail}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="pt-2 border-t border-slate-100 dark:border-border">
                      <button
                        onClick={() => {
                          sessionStorage.setItem("azureResourcesDeepDive", buildDeepDivePrompt());
                          navigate("/ai-chats");
                        }}
                        className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                      >
                        Deep dive in chat →
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </DataPanel>
        )}

        {status?.features?.azure_monitor?.enabled && monitorData && (
          <DataPanel
            title={`Azure Monitor — ${monitorData.metrics?.length ?? 0} data points (last 1h)`}
            icon={<Activity className="h-4 w-4 text-purple-500" />}
            expanded={expandedPanels["monitor"]}
            onToggle={() => togglePanel("monitor")}
          >
            {!monitorData.metrics?.length ? (
              <p className="text-sm text-slate-500 dark:text-muted-foreground">No metrics returned. Ensure Container Insights is enabled on your AKS cluster.</p>
            ) : (
              <div className="space-y-3">
                {(["node_cpu_usage_percentage", "node_memory_rss_percentage"] as const).map((metricName) => {
                  const points = monitorData.metrics.filter((m: any) => m.metric === metricName);
                  if (!points.length) return null;
                  const latest = points[points.length - 1];
                  const avg = points.reduce((s: number, p: any) => s + (p.average ?? 0), 0) / points.length;
                  const label = metricName === "node_cpu_usage_percentage" ? "CPU Usage" : "Memory RSS";
                  const color = metricName === "node_cpu_usage_percentage" ? "bg-blue-500" : "bg-purple-500";
                  return (
                    <div key={metricName}>
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="font-medium text-slate-700 dark:text-foreground">{label}</span>
                        <span className="text-slate-500 dark:text-muted-foreground">
                          Latest: {latest.average != null ? `${latest.average.toFixed(1)}%` : "—"} &nbsp;·&nbsp; Avg: {avg.toFixed(1)}%
                        </span>
                      </div>
                      <div className="w-full h-2 bg-slate-100 dark:bg-muted rounded-full overflow-hidden">
                        <div
                          className={`h-2 rounded-full ${color}`}
                          style={{ width: `${Math.min(latest.average ?? 0, 100)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </DataPanel>
        )}

        {status?.features?.cost_anomaly_alerting?.enabled && anomaliesData && (
          <DataPanel
            title={`Cost Anomalies (${anomaliesData.count})`}
            expanded={expandedPanels["anomalies"]}
            onToggle={() => togglePanel("anomalies")}
          >
            {anomaliesData.count === 0 ? (
              <p className="text-sm text-slate-500 dark:text-muted-foreground">No anomalies detected.</p>
            ) : (
              <ul className="space-y-2">
                {anomaliesData.anomalies.map((a: any, i: number) => (
                  <li key={i} className="text-xs text-slate-700 dark:text-foreground bg-slate-50 dark:bg-muted rounded-lg px-3 py-2">
                    <span className="font-medium">{a.name}</span> — {a.status} — {a.time_created}
                  </li>
                ))}
              </ul>
            )}
          </DataPanel>
        )}

        {status?.features?.ai_cost_recommendations?.enabled && recommendationsData && (
          <DataPanel
            title={`Azure Advisor Recommendations (${recommendationsData.count})`}
            expanded={expandedPanels["recommendations"]}
            onToggle={() => togglePanel("recommendations")}
          >
            {recommendationsData.count === 0 ? (
              <p className="text-sm text-slate-500 dark:text-muted-foreground">No cost recommendations found.</p>
            ) : (
              <ul className="space-y-2">
                {recommendationsData.recommendations.map((r: any, i: number) => (
                  <li key={i} className="text-xs text-slate-700 dark:text-foreground bg-slate-50 dark:bg-muted rounded-lg px-3 py-2">
                    <span className="font-medium">{r.short_description}</span>
                    <span className="ml-2 text-slate-400">Impact: {r.impact}</span>
                  </li>
                ))}
              </ul>
            )}
          </DataPanel>
        )}
      </div>

      {/* Disconnect confirmation */}
      {showDisconnectConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white dark:bg-card rounded-xl shadow-xl border border-slate-200 dark:border-border p-6 max-w-sm w-full mx-4">
            <h2 className="font-semibold text-slate-900 dark:text-foreground mb-2">Disconnect Azure?</h2>
            <p className="text-sm text-slate-500 dark:text-muted-foreground mb-5">
              This will delete your stored credentials and disable all Azure features.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowDisconnectConfirm(false)}
                className="px-4 py-2 rounded-lg text-sm text-slate-600 dark:text-muted-foreground hover:bg-slate-100 dark:hover:bg-accent transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="px-4 py-2 rounded-lg text-sm bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {disconnecting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Disconnect
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
      </div>
    </div>
  );
}

function DataPanel({
  title,
  icon,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-border bg-white dark:bg-card overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-700 dark:text-foreground hover:bg-slate-50 dark:hover:bg-accent transition-colors"
      >
        <span className="flex items-center gap-2">
          {icon}
          {title}
        </span>
        {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>
      {expanded && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}
