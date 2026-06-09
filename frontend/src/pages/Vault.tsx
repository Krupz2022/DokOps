import { useEffect, useState } from "react";
import { Lock, Plus, Edit2, Trash2, ChevronDown, ChevronRight, Check, Tag } from "lucide-react";
import api from "../lib/api";

interface ClusterCoverage {
  cluster_id: string;
  cluster_name: string;
  provider: string;
  configured: string[];
  total_services: number;
}

interface Credential {
  id: string;
  scope_type: string;
  scope_id: string;
  service_type: string;
  instance_name: string;
  username: string;
  host: string | null;
  port: number | null;
  created_at: string;
}

interface ServiceConfig {
  label: string;
  icon: string;
  required: string[];
  advanced: { key: string; label: string; default: string }[];
  extraKeys: string[];
}

const SERVICE_CONFIGS: Record<string, ServiceConfig> = {
  rabbitmq: {
    label: "RabbitMQ",
    icon: "/service-icons/rabbitmq.svg",
    required: ["host", "username", "password"],
    advanced: [
      { key: "port", label: "AMQP Port", default: "5672" },
      { key: "management_port", label: "Mgmt Port", default: "15672" },
      { key: "vhost", label: "VHost", default: "/" },
    ],
    extraKeys: ["vhost", "management_port"],
  },
  redis: {
    label: "Redis",
    icon: "/service-icons/redis.svg",
    required: ["host", "password"],
    advanced: [
      { key: "port", label: "Port", default: "6379" },
      { key: "username", label: "Username", default: "" },
      { key: "db_index", label: "DB Index", default: "0" },
    ],
    extraKeys: ["db_index"],
  },
  couchdb: {
    label: "CouchDB",
    icon: "/service-icons/couchdb.svg",
    required: ["host", "username", "password"],
    advanced: [{ key: "port", label: "Port", default: "5984" }],
    extraKeys: [],
  },
  mongodb: {
    label: "MongoDB",
    icon: "/service-icons/mongodb.svg",
    required: ["host", "username", "password"],
    advanced: [
      { key: "port", label: "Port", default: "27017" },
      { key: "auth_db", label: "Auth DB", default: "admin" },
    ],
    extraKeys: ["auth_db"],
  },
  postgres: {
    label: "Postgres",
    icon: "/service-icons/postgres.svg",
    required: ["host", "username", "password"],
    advanced: [
      { key: "port", label: "Port", default: "5432" },
      { key: "database", label: "Database", default: "" },
    ],
    extraKeys: ["database"],
  },
  mysql: {
    label: "MySQL",
    icon: "/service-icons/mysql.svg",
    required: ["host", "username", "password"],
    advanced: [
      { key: "port", label: "Port", default: "3306" },
      { key: "database", label: "Database", default: "" },
    ],
    extraKeys: ["database"],
  },
  mssql: {
    label: "SQL Server",
    icon: "/service-icons/mssqlserver.svg",
    required: ["host", "username", "password"],
    advanced: [
      { key: "port", label: "Port", default: "1433" },
      { key: "database", label: "Default DB", default: "" },
    ],
    extraKeys: ["database"],
  },
};

const SERVICES = Object.keys(SERVICE_CONFIGS);

export default function Vault() {
  const [coverage, setCoverage] = useState<ClusterCoverage[]>([]);
  const [selectedCluster, setSelectedCluster] = useState<ClusterCoverage | null>(null);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [editingService, setEditingService] = useState<string | null>(null);
  const [editingCredentialId, setEditingCredentialId] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get("/vault/coverage").then((res) => {
      const data = res.data as ClusterCoverage[];
      setCoverage(data);
      if (data.length > 0) selectCluster(data[0]);
    });
  }, []);

  function selectCluster(cluster: ClusterCoverage) {
    setSelectedCluster(cluster);
    setEditingService(null);
    setEditingCredentialId(null);
    api
      .get(`/service-credentials/?scope_type=cluster&scope_id=${cluster.cluster_id}`)
      .then((res) => setCredentials(res.data as Credential[]));
  }

  function startAddInstance(serviceType: string) {
    const config = SERVICE_CONFIGS[serviceType];
    const defaults: Record<string, string> = { instance_name: "" };
    config.required.forEach((f) => (defaults[f] = ""));
    config.advanced.forEach((f) => (defaults[f.key] = f.default));
    setFormData(defaults);
    setEditingService(serviceType);
    setEditingCredentialId(null);
    setShowAdvanced(false);
    setError(null);
  }

  function startEditInstance(serviceType: string, cred: Credential) {
    const config = SERVICE_CONFIGS[serviceType];
    const defaults: Record<string, string> = {
      instance_name: cred.instance_name || "",
      host: cred.host || "",
      username: cred.username.replace("***", ""),
      password: "",
    };
    config.advanced.forEach((f) => (defaults[f.key] = f.default));
    setFormData(defaults);
    setEditingService(serviceType);
    setEditingCredentialId(cred.id);
    setShowAdvanced(false);
    setError(null);
  }

  async function saveCredential() {
    if (!selectedCluster || !editingService) return;
    setSaving(true);
    setError(null);
    const config = SERVICE_CONFIGS[editingService];
    const extra: Record<string, string> = {};
    config.extraKeys.forEach((k) => {
      if (formData[k]) extra[k] = formData[k];
    });
    const port = formData.port ? parseInt(formData.port) : null;
    const payload = {
      scope_type: "cluster",
      scope_id: selectedCluster.cluster_id,
      service_type: editingService,
      instance_name: formData.instance_name || "",
      username: formData.username || "",
      password: formData.password || "",
      host: formData.host || null,
      port,
      extra: JSON.stringify(extra),
    };
    try {
      if (editingCredentialId) {
        await api.put(`/service-credentials/${editingCredentialId}`, payload);
      } else {
        await api.post("/service-credentials/", payload);
      }
      setEditingService(null);
      setEditingCredentialId(null);
      selectCluster(selectedCluster);
      api.get("/vault/coverage").then((res) => setCoverage(res.data as ClusterCoverage[]));
    } catch {
      setError("Failed to save credential. Check God Mode is enabled.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteCredential(cred: Credential) {
    if (!selectedCluster) return;
    await api.delete(`/service-credentials/${cred.id}`);
    if (editingCredentialId === cred.id) {
      setEditingService(null);
      setEditingCredentialId(null);
    }
    selectCluster(selectedCluster);
    api.get("/vault/coverage").then((res) => setCoverage(res.data as ClusterCoverage[]));
  }

  function coverageBadge(cluster: ClusterCoverage) {
    const count = cluster.configured.length;
    const total = cluster.total_services;
    const color =
      count === 0
        ? "bg-red-900/40 text-red-400"
        : count === total
        ? "bg-green-900/40 text-green-400"
        : "bg-yellow-900/40 text-yellow-400";
    return (
      <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${color}`}>
        {count}/{total}
      </span>
    );
  }

  return (
    <div className="flex h-full bg-background text-foreground">
      {/* Cluster List */}
      <div className="w-56 flex-shrink-0 border-r border-border flex flex-col">
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Lock size={14} className="text-cyan-400" />
            <span className="text-sm font-semibold text-foreground">Vault</span>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">Cluster-scoped credentials</p>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-1">
          {coverage.map((cluster) => (
            <button
              key={cluster.cluster_id}
              onClick={() => selectCluster(cluster)}
              className={`w-full text-left rounded-md px-3 py-2 transition-colors ${
                selectedCluster?.cluster_id === cluster.cluster_id
                  ? "bg-secondary border border-cyan-500/40"
                  : "hover:bg-secondary/50 border border-transparent"
              }`}
            >
              <div className="flex justify-between items-center">
                <span className="text-xs font-medium text-foreground truncate">{cluster.cluster_name}</span>
                {coverageBadge(cluster)}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">{cluster.provider.toUpperCase()}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Credential Manager */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {selectedCluster ? (
          <>
            <div className="px-5 py-3 border-b border-border flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-foreground">
                  {selectedCluster.cluster_name} · Credentials
                </h2>
                <p className="text-xs text-muted-foreground">
                  {selectedCluster.configured.length} of {selectedCluster.total_services} services configured
                </p>
              </div>
            </div>

            <div className="flex-1 overflow-auto p-5">
              <div className="grid grid-cols-3 gap-3 mb-5">
                {SERVICES.map((svc) => {
                  const config = SERVICE_CONFIGS[svc];
                  const svcCreds = credentials.filter((c) => c.service_type === svc);
                  const isConfigured = svcCreds.length > 0;
                  return (
                    <div
                      key={svc}
                      className={`rounded-lg p-3 border transition-colors ${
                        isConfigured
                          ? "border-green-500/40 bg-secondary/30"
                          : "border-border bg-secondary/30 opacity-70"
                      }`}
                    >
                      {/* Card header */}
                      <div className="flex justify-between items-start mb-2">
                        {config.icon.startsWith("/") ? (
                          <img src={config.icon} alt={config.label} className="w-7 h-7 object-contain" />
                        ) : (
                          <span className="text-xl">{config.icon}</span>
                        )}
                        {isConfigured ? (
                          <span className="text-xs bg-green-500/10 text-green-400 border border-green-500/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                            <Check size={10} /> {svcCreds.length} instance{svcCreds.length !== 1 ? "s" : ""}
                          </span>
                        ) : (
                          <span className="text-xs bg-secondary text-muted-foreground px-2 py-0.5 rounded-full">
                            empty
                          </span>
                        )}
                      </div>
                      <p className="text-xs font-medium text-foreground mb-2">{config.label}</p>

                      {/* Instance list */}
                      {svcCreds.length > 0 && (
                        <div className="space-y-1 mb-2">
                          {svcCreds.map((cred) => (
                            <div
                              key={cred.id}
                              className="flex items-center gap-1 bg-background/40 rounded px-2 py-1"
                            >
                              <Tag size={9} className="text-cyan-500/60 flex-shrink-0" />
                              <span className="text-xs text-muted-foreground truncate flex-1">
                                {cred.instance_name ? (
                                  <span className="text-cyan-400/80">{cred.instance_name}</span>
                                ) : (
                                  <span className="italic">{cred.host || "default"}</span>
                                )}
                              </span>
                              <button
                                onClick={() => startEditInstance(svc, cred)}
                                className="text-foreground/40 hover:text-foreground/80 flex-shrink-0"
                                title="Edit"
                              >
                                <Edit2 size={10} />
                              </button>
                              <button
                                onClick={() => deleteCredential(cred)}
                                className="text-red-400/50 hover:text-red-400 flex-shrink-0"
                                title="Delete"
                              >
                                <Trash2 size={10} />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Add instance button */}
                      <button
                        onClick={() => startAddInstance(svc)}
                        className="w-full text-xs bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 px-2 py-1 rounded flex items-center justify-center gap-1"
                      >
                        <Plus size={10} /> Add instance
                      </button>
                    </div>
                  );
                })}
              </div>

              {/* Inline edit/add form */}
              {editingService && (
                <div className="rounded-lg border border-cyan-500/20 bg-secondary/30 p-4">
                  <h3 className="text-xs font-semibold text-foreground mb-3">
                    {editingCredentialId ? "Edit" : "Add"} instance ·{" "}
                    {SERVICE_CONFIGS[editingService].label} · {selectedCluster.cluster_name}
                  </h3>

                  {/* Instance name */}
                  <div className="mb-3">
                    <label className="text-xs text-muted-foreground uppercase tracking-wide mb-1 block">
                      Instance Name <span className="normal-case text-muted-foreground/50">(optional — e.g. "cache", "sessions")</span>
                    </label>
                    <input
                      type="text"
                      value={formData.instance_name || ""}
                      onChange={(e) => setFormData({ ...formData, instance_name: e.target.value })}
                      placeholder='Leave empty for default (e.g. "cache", "sessions", "analytics")'
                      className="w-full bg-background border border-border rounded px-2 py-1.5 text-xs text-foreground focus:outline-none focus:border-cyan-500"
                    />
                  </div>

                  {/* Required fields */}
                  <div className="grid grid-cols-3 gap-3 mb-3">
                    {SERVICE_CONFIGS[editingService].required.map((field) => (
                      <div key={field}>
                        <label className="text-xs text-muted-foreground uppercase tracking-wide mb-1 block">
                          {field}
                        </label>
                        <input
                          type={field === "password" ? "password" : "text"}
                          value={formData[field] || ""}
                          onChange={(e) => setFormData({ ...formData, [field]: e.target.value })}
                          placeholder={field === "host" ? "e.g. redis.infra.example.com" : field === "password" && editingCredentialId ? "(leave blank to keep)" : ""}
                          className="w-full bg-background border border-border rounded px-2 py-1.5 text-xs text-foreground focus:outline-none focus:border-cyan-500"
                        />
                      </div>
                    ))}
                  </div>

                  {/* Advanced toggle */}
                  {SERVICE_CONFIGS[editingService].advanced.length > 0 && (
                    <button
                      onClick={() => setShowAdvanced(!showAdvanced)}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-3"
                    >
                      {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      Advanced
                    </button>
                  )}
                  {showAdvanced && (
                    <div className="grid grid-cols-4 gap-3 mb-3">
                      {SERVICE_CONFIGS[editingService].advanced.map((field) => (
                        <div key={field.key}>
                          <label className="text-xs text-muted-foreground uppercase tracking-wide mb-1 block">
                            {field.label}
                          </label>
                          <input
                            type="text"
                            value={formData[field.key] || field.default}
                            onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                            placeholder={field.default}
                            className="w-full bg-background border border-border rounded px-2 py-1.5 text-xs text-foreground focus:outline-none focus:border-cyan-500"
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  {error && <p className="text-xs text-red-400 mb-3">{error}</p>}

                  <div className="flex items-center gap-2">
                    <button
                      onClick={saveCredential}
                      disabled={saving}
                      className="text-xs bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-4 py-1.5 rounded"
                    >
                      {saving ? "Saving..." : "Save"}
                    </button>
                    <button
                      onClick={() => { setEditingService(null); setEditingCredentialId(null); }}
                      className="text-xs bg-secondary hover:bg-secondary/70 text-foreground/70 px-4 py-1.5 rounded"
                    >
                      Cancel
                    </button>
                    <div className="flex-1" />
                    <p className="text-xs text-muted-foreground/40 font-mono">
                      instance_name used as selector when calling tools
                    </p>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground/50">
            <p className="text-sm">Select a cluster to manage credentials</p>
          </div>
        )}
      </div>
    </div>
  );
}
