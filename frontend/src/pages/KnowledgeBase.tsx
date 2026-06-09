import { useEffect, useRef, useState, useCallback } from "react";
import api from "../lib/api";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { RefreshCw, Upload, Link, Trash2, Database, Loader2, X } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";

interface PendingJob {
  jobId: string;
  title: string;
  status: "queued" | "processing" | "indexed" | "failed";
  error?: string;
}

interface RagDocument {
  id: string;
  title: string;
  source_type: "runbook" | "upload" | "external_url" | "incident" | "confluence";
  source_ref: string;
  chunk_count: number;
  status: "indexed" | "failed" | "pending";
  indexed_at: string;
}

interface ConfluenceConfig {
  instance_type: "cloud" | "server_basic" | "server_pat";
  base_url: string;
  email: string;
  username: string;
  api_token: string;
  sync_spaces: string;
  sync_interval_hours: string;
}

const DEFAULT_CONFLUENCE_CONFIG: ConfluenceConfig = {
  instance_type: "cloud",
  base_url: "",
  email: "",
  username: "",
  api_token: "",
  sync_spaces: "",
  sync_interval_hours: "24",
};

const SOURCE_TYPE_LABEL: Record<string, string> = {
  runbook: "Runbook",
  upload: "Upload",
  external_url: "URL",
  incident: "Incident",
  confluence: "Confluence",
};

export default function KnowledgeBase() {
  const [docs, setDocs] = useState<RagDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncingRunbooks, setSyncingRunbooks] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [addingUrl, setAddingUrl] = useState(false);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [pendingJobs, setPendingJobs] = useState<PendingJob[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const [confluenceConfig, setConfluenceConfig] = useState<ConfluenceConfig>(DEFAULT_CONFLUENCE_CONFIG);
  const [confluenceTab, setConfluenceTab] = useState<"config" | "sync">("config");
  const [confluenceSpacesInput, setConfluenceSpacesInput] = useState("");
  const [savingConfluence, setSavingConfluence] = useState(false);
  const [testingConfluence, setTestingConfluence] = useState(false);
  const [confluenceTestResult, setConfluenceTestResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [confluenceSyncingSpace, setConfluenceSyncingSpace] = useState<string | null>(null);
  const [confluencePageUrl, setConfluencePageUrl] = useState("");
  const [ingestingPage, setIngestingPage] = useState(false);
  const { toast } = useToast();
  const { confirm } = useConfirm();

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/rag/documents");
      setDocs(res.data);
    } catch (err) {
      console.error("Failed to fetch RAG documents", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const addPendingJob = (jobId: string, title: string) => {
    setPendingJobs((prev) => [...prev, { jobId, title, status: "queued" }]);
  };

  // Poll all active jobs every 2s
  useEffect(() => {
    const active = pendingJobs.filter((j) => j.status === "queued" || j.status === "processing");
    if (active.length === 0) return;
    const interval = setInterval(async () => {
      const updates = await Promise.all(
        active.map(async (job) => {
          try {
            const res = await api.get(`/rag/jobs/${job.jobId}`);
            return { jobId: job.jobId, status: res.data.status, error: res.data.error };
          } catch {
            return { jobId: job.jobId, status: "failed", error: "Job not found" };
          }
        })
      );
      let anyCompleted = false;
      setPendingJobs((prev) =>
        prev.map((job) => {
          const update = updates.find((u) => u.jobId === job.jobId);
          if (!update) return job;
          if (update.status === "indexed" || update.status === "failed") {
            anyCompleted = true;
            if (update.status === "failed") {
              toast(`Indexing failed for "${job.title}": ${update.error || "unknown error"}`, "error");
            }
          }
          return { ...job, status: update.status as PendingJob["status"], error: update.error };
        })
      );
      if (anyCompleted) fetchDocs();
    }, 2000);
    return () => clearInterval(interval);
  }, [pendingJobs, fetchDocs]);

  // Auto-remove only successfully indexed jobs after 4s; failed jobs stay until manually dismissed
  useEffect(() => {
    const indexed = pendingJobs.filter((j) => j.status === "indexed");
    if (indexed.length === 0) return;
    const timeout = setTimeout(() => {
      setPendingJobs((prev) => prev.filter((j) => j.status !== "indexed"));
    }, 4000);
    return () => clearTimeout(timeout);
  }, [pendingJobs]);

  const dismissJob = (jobId: string) => {
    setPendingJobs((prev) => prev.filter((j) => j.jobId !== jobId));
  };

  const loadConfluenceConfig = async () => {
    try {
      const res = await api.get("/rag/confluence/config");
      const d = res.data;
      let spacesStr = "";
      if (d.sync_spaces) {
        try {
          spacesStr = (JSON.parse(d.sync_spaces) as string[]).join(", ");
        } catch {
          spacesStr = d.sync_spaces;
        }
      }
      const cfg: ConfluenceConfig = {
        instance_type: (d.instance_type as ConfluenceConfig["instance_type"]) || "cloud",
        base_url: d.base_url || "",
        email: d.email || "",
        username: d.username || "",
        api_token: d.api_token || "",
        sync_spaces: spacesStr,
        sync_interval_hours: d.sync_interval_hours || "24",
      };
      setConfluenceConfig(cfg);
      setConfluenceSpacesInput(spacesStr);
    } catch {
      // Not configured yet — keep defaults
    }
  };

  const handleSaveConfluenceConfig = async () => {
    setSavingConfluence(true);
    try {
      const spaces = confluenceSpacesInput
        .split(",")
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);
      await api.post("/rag/confluence/config", {
        instance_type: confluenceConfig.instance_type,
        base_url: confluenceConfig.base_url,
        email: confluenceConfig.email,
        username: confluenceConfig.username,
        api_token: confluenceConfig.api_token === "••••••" ? "" : confluenceConfig.api_token,
        sync_spaces: spaces,
        sync_interval_hours: parseInt(confluenceConfig.sync_interval_hours, 10) || 0,
      });
      setConfluenceConfig((prev) => ({ ...prev, sync_spaces: spaces.join(", ") }));
      setConfluenceSpacesInput(spaces.join(", "));
      toast("Confluence configuration saved.", "success");
    } catch (err: any) {
      toast(`Save failed: ${err.response?.data?.detail || err.message}`, "error");
    } finally {
      setSavingConfluence(false);
    }
  };

  const handleTestConfluence = async () => {
    setTestingConfluence(true);
    setConfluenceTestResult(null);
    try {
      await api.post("/rag/confluence/test");
      setConfluenceTestResult({ ok: true, detail: "Connected" });
    } catch (err: any) {
      setConfluenceTestResult({ ok: false, detail: err.response?.data?.detail || err.message });
    } finally {
      setTestingConfluence(false);
    }
  };

  const handleSyncSpace = async (spaceKey: string) => {
    setConfluenceSyncingSpace(spaceKey);
    try {
      const res = await api.post("/rag/ingest/confluence/space", { space_key: spaceKey });
      toast(`Synced ${res.data.synced} page(s) from ${spaceKey}.${res.data.failed ? ` ${res.data.failed} failed.` : ""}`, "success");
      fetchDocs();
    } catch (err: any) {
      toast(`Sync failed: ${err.response?.data?.detail || err.message}`, "error");
    } finally {
      setConfluenceSyncingSpace(null);
    }
  };

  const handleIngestPage = async () => {
    if (!confluencePageUrl.trim()) return;
    setIngestingPage(true);
    try {
      const res = await api.post("/rag/ingest/confluence/page", { url: confluencePageUrl.trim() });
      toast(`Indexed: ${res.data.title}`, "success");
      setConfluencePageUrl("");
      fetchDocs();
    } catch (err: any) {
      toast(`Failed: ${err.response?.data?.detail || err.message}`, "error");
    } finally {
      setIngestingPage(false);
    }
  };

  const getLastSyncedForSpace = (spaceKey: string): string => {
    const spaceDocs = docs.filter(
      (d) => d.source_type === "confluence" && d.source_ref.includes(`/spaces/${spaceKey}/`)
    );
    if (spaceDocs.length === 0) return "Never";
    const latest = spaceDocs.reduce((a, b) =>
      new Date(a.indexed_at) > new Date(b.indexed_at) ? a : b
    );
    return formatDate(latest.indexed_at);
  };

  useEffect(() => {
    fetchDocs();
    loadConfluenceConfig();
  }, []);

  const handleSyncRunbooks = async () => {
    setSyncingRunbooks(true);
    try {
      const res = await api.post("/rag/ingest/runbooks");
      toast(`Synced ${res.data.synced} runbook(s).`, "success");
      fetchDocs();
    } catch (err: any) {
      toast(`Sync failed: ${err.response?.data?.detail || err.message}`, "error");
    } finally {
      setSyncingRunbooks(false);
    }
  };

  const handleAddUrl = async () => {
    if (!urlInput.trim()) return;
    setAddingUrl(true);
    try {
      const res = await api.post("/rag/ingest/url", { url: urlInput.trim() });
      addPendingJob(res.data.job_id, res.data.title || urlInput.trim());
      setUrlInput("");
      toast("URL queued for indexing.", "success");
    } catch (err: any) {
      toast(`Failed to index URL: ${err.response?.data?.detail || err.message}`, "error");
    } finally {
      setAddingUrl(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingFile(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api.post("/rag/ingest/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      addPendingJob(res.data.job_id, res.data.title || file.name);
      toast("File queued for indexing.", "success");
    } catch (err: any) {
      toast(`Upload failed: ${err.response?.data?.detail || err.message}`, "error");
    } finally {
      setUploadingFile(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleDelete = async (docId: string) => {
    const ok = await confirm({
      title: "Remove Document",
      description: "This document will be removed from the knowledge base and will no longer be available for AI context.",
      variant: "danger",
      confirmLabel: "Remove",
    });
    if (!ok) return;
    try {
      await api.delete(`/rag/documents/${docId}`);
      setDocs((prev) => prev.filter((d) => d.id !== docId));
    } catch (err: any) {
      toast(`Delete failed: ${err.response?.data?.detail || err.message}`, "error");
    }
  };

  const formatDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-foreground">Knowledge Base</h1>
          <p className="text-sm text-slate-500 dark:text-muted-foreground mt-0.5">
            Documents indexed for RAG-augmented AI responses
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="outline" onClick={handleSyncRunbooks} disabled={syncingRunbooks}>
            <RefreshCw className={`w-4 h-4 mr-2 ${syncingRunbooks ? "animate-spin" : ""}`} />
            {syncingRunbooks ? "Syncing..." : "Sync Runbooks"}
          </Button>
          <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={uploadingFile}>
            <Upload className="w-4 h-4 mr-2" />
            {uploadingFile ? "Uploading..." : "Upload File"}
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.md,.txt,.markdown"
            className="hidden"
            onChange={handleFileUpload}
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
      <div className="space-y-6">
      {/* Add URL */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Link className="w-4 h-4" />
            Add External URL
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              placeholder="https://kubernetes.io/docs/..."
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddUrl()}
            />
            <Button onClick={handleAddUrl} disabled={addingUrl || !urlInput.trim()}>
              {addingUrl ? "Indexing..." : "Add URL"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Confluence */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Database className="w-4 h-4 text-blue-500" />
            Confluence Knowledge Sync
          </CardTitle>
          <div className="flex gap-1 mt-2">
            {(["config", "sync"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setConfluenceTab(tab)}
                className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
                  confluenceTab === tab
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80"
                }`}
              >
                {tab === "config" ? "Configuration" : "Sync"}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {confluenceTab === "config" && (
            <>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Instance Type</label>
                <div className="flex gap-2">
                  {(["cloud", "server_basic", "server_pat"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setConfluenceConfig((p) => ({ ...p, instance_type: t }))}
                      className={`px-3 py-1 text-xs rounded border transition-colors ${
                        confluenceConfig.instance_type === t
                          ? "border-primary bg-primary/10 text-primary font-medium"
                          : "border-border text-muted-foreground hover:border-primary/50"
                      }`}
                    >
                      {t === "cloud" ? "Cloud" : t === "server_basic" ? "Server (Basic)" : "Server (PAT)"}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Base URL</label>
                <Input
                  placeholder="https://yourorg.atlassian.net"
                  value={confluenceConfig.base_url}
                  onChange={(e) => setConfluenceConfig((p) => ({ ...p, base_url: e.target.value }))}
                />
              </div>

              {confluenceConfig.instance_type === "cloud" && (
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">Email</label>
                  <Input
                    placeholder="user@yourorg.com"
                    value={confluenceConfig.email}
                    onChange={(e) => setConfluenceConfig((p) => ({ ...p, email: e.target.value }))}
                  />
                </div>
              )}

              {confluenceConfig.instance_type === "server_basic" && (
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">Username</label>
                  <Input
                    placeholder="username"
                    value={confluenceConfig.username}
                    onChange={(e) => setConfluenceConfig((p) => ({ ...p, username: e.target.value }))}
                  />
                </div>
              )}

              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {confluenceConfig.instance_type === "cloud"
                    ? "API Token"
                    : confluenceConfig.instance_type === "server_basic"
                    ? "Password"
                    : "Personal Access Token"}
                </label>
                <Input
                  type="password"
                  placeholder={confluenceConfig.instance_type === "cloud" ? "Your Atlassian API token" : "••••••••"}
                  value={confluenceConfig.api_token}
                  onChange={(e) => setConfluenceConfig((p) => ({ ...p, api_token: e.target.value }))}
                />
              </div>

              <div className="flex items-center gap-3">
                <Button variant="outline" size="sm" onClick={handleTestConfluence} disabled={testingConfluence}>
                  {testingConfluence ? "Testing..." : "Test Connection"}
                </Button>
                {confluenceTestResult && (
                  <span className={`text-xs font-medium ${confluenceTestResult.ok ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
                    {confluenceTestResult.ok ? "✓ Connected" : `✗ ${confluenceTestResult.detail}`}
                  </span>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Space Keys</label>
                <Input
                  placeholder="ENG, DEVOPS, PLATFORM"
                  value={confluenceSpacesInput}
                  onChange={(e) => setConfluenceSpacesInput(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">Comma-separated. Each key syncs all pages in that space.</p>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Auto-Sync Interval</label>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
                  value={confluenceConfig.sync_interval_hours}
                  onChange={(e) => setConfluenceConfig((p) => ({ ...p, sync_interval_hours: e.target.value }))}
                >
                  <option value="0">Manual only</option>
                  <option value="6">Every 6 hours</option>
                  <option value="12">Every 12 hours</option>
                  <option value="24">Every 24 hours</option>
                </select>
              </div>

              <Button onClick={handleSaveConfluenceConfig} disabled={savingConfluence}>
                {savingConfluence ? "Saving..." : "Save Configuration"}
              </Button>
            </>
          )}

          {confluenceTab === "sync" && (
            <>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Configured Spaces</p>
                {confluenceSpacesInput
                  .split(",")
                  .map((s) => s.trim().toUpperCase())
                  .filter(Boolean)
                  .map((spaceKey) => (
                    <div key={spaceKey} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                      <div>
                        <span className="text-sm font-mono font-medium">{spaceKey}</span>
                        <span className="ml-3 text-xs text-muted-foreground">
                          Last synced: {getLastSyncedForSpace(spaceKey)}
                        </span>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleSyncSpace(spaceKey)}
                        disabled={confluenceSyncingSpace !== null}
                      >
                        <RefreshCw className={`w-3 h-3 mr-1 ${confluenceSyncingSpace === spaceKey ? "animate-spin" : ""}`} />
                        {confluenceSyncingSpace === spaceKey ? "Syncing..." : "Sync Now"}
                      </Button>
                    </div>
                  ))}
                {!confluenceSpacesInput.trim() && (
                  <p className="text-xs text-muted-foreground italic">
                    No spaces configured. Add space keys in the Configuration tab.
                  </p>
                )}
              </div>

              <div className="space-y-1 pt-2 border-t border-border">
                <p className="text-xs font-medium text-muted-foreground">Ingest Individual Page</p>
                <div className="flex gap-2">
                  <Input
                    placeholder="https://yourorg.atlassian.net/wiki/spaces/ENG/pages/12345/..."
                    value={confluencePageUrl}
                    onChange={(e) => setConfluencePageUrl(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleIngestPage()}
                  />
                  <Button onClick={handleIngestPage} disabled={ingestingPage || !confluencePageUrl.trim()}>
                    {ingestingPage ? "Indexing..." : "Ingest Page"}
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Documents table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Database className="w-4 h-4" />
            Indexed Documents ({docs.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 text-center text-slate-500 dark:text-muted-foreground text-sm">
              Loading...
            </div>
          ) : docs.length === 0 ? (
            <div className="p-6 text-center text-slate-500 dark:text-muted-foreground text-sm">
              No documents indexed yet. Sync runbooks, upload a file, or add a URL.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-border bg-slate-50 dark:bg-muted/30">
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-muted-foreground">Title</th>
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-muted-foreground">Type</th>
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-muted-foreground">Chunks</th>
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-muted-foreground">Status</th>
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-muted-foreground">Indexed At</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {pendingJobs.map((job) => (
                    <tr
                      key={job.jobId}
                      className="border-b border-slate-100 dark:border-border bg-blue-50/40 dark:bg-blue-950/10"
                    >
                      <td className="px-4 py-3 font-medium text-slate-800 dark:text-foreground max-w-xs truncate flex items-center gap-2">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500 flex-shrink-0" />
                        {job.title}
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 dark:bg-muted text-slate-600 dark:text-muted-foreground">
                          —
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-400 dark:text-muted-foreground">—</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                            job.status === "indexed"
                              ? "bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-400"
                              : job.status === "failed"
                              ? "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400"
                              : "bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400"
                          }`}
                        >
                          {job.status === "queued" ? "queued" : job.status === "processing" ? "indexing..." : job.status}
                        </span>
                        {job.status === "failed" && job.error && (
                          <span className="ml-2 text-xs text-red-500 truncate max-w-xs">{job.error}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-400 dark:text-muted-foreground text-xs">—</td>
                      <td className="px-4 py-3">
                        {(job.status === "failed") && (
                          <button
                            onClick={() => dismissJob(job.jobId)}
                            className="text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                            title="Dismiss"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {docs.map((doc) => (
                    <tr
                      key={doc.id}
                      className="border-b border-slate-100 dark:border-border hover:bg-slate-50 dark:hover:bg-muted/20 transition-colors"
                    >
                      <td className="px-4 py-3 font-medium text-slate-800 dark:text-foreground max-w-xs truncate">
                        {doc.title}
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 dark:bg-muted text-slate-600 dark:text-muted-foreground">
                          {SOURCE_TYPE_LABEL[doc.source_type] ?? doc.source_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600 dark:text-muted-foreground">{doc.chunk_count}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                            doc.status === "indexed"
                              ? "bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-400"
                              : doc.status === "failed"
                              ? "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400"
                              : "bg-yellow-100 text-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-400"
                          }`}
                        >
                          {doc.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-muted-foreground text-xs whitespace-nowrap">
                        {formatDate(doc.indexed_at)}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleDelete(doc.id)}
                          className="text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                          title="Delete document"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
      </div>
      </div>
    </div>
  );
}
