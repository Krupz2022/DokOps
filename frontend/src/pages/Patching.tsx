import { useEffect, useState } from "react";
import api from "../lib/api";

interface DeviceRow {
  minion_id: string; hostname: string; status: string; os_family: string;
  total_patches: number; critical: number; high: number;
  last_scanned: string | null;
}
interface CveRow {
  advisory_id: string | null; package_name: string; severity: string;
  advisory_type: string; cve_ids: string[]; affected_minion_ids: string[];
}
interface PatchDetail {
  package_name: string; installed_version: string; available_version: string;
  advisory_id: string | null; advisory_type: string; severity: string; cve_ids: string[];
}

const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-red-900/50 text-red-300 border-red-800",
  high:     "bg-orange-900/50 text-orange-300 border-orange-800",
  medium:   "bg-yellow-900/50 text-yellow-300 border-yellow-800",
  low:      "bg-blue-900/50 text-blue-300 border-blue-800",
  none:     "bg-muted text-muted-foreground border-border",
};

const TYPE_LABEL: Record<string, string> = {
  security:    "Security",
  bugfix:      "Bug Fix",
  enhancement: "Enhancement",
};

const OS_ICON: Record<string, string> = {
  windows: "⊞",
  linux:   "🐧",
  unknown: "?",
};

const ADVISORY_TYPES = ["security", "bugfix", "enhancement"] as const;

export default function Patching() {
  const [tab, setTab] = useState<"device" | "cve">("device");
  const [devices, setDevices] = useState<DeviceRow[]>([]);
  const [cves, setCves] = useState<CveRow[]>([]);
  const [loading, setLoading] = useState(true);

  // global advisory-type filter (applies to device drill-down and CVE tab)
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());

  // CVE severity filter
  const [severityFilter, setSeverityFilter] = useState<string>("all");

  // device drill-down panel
  const [selectedDevice, setSelectedDevice] = useState<DeviceRow | null>(null);
  const [devicePatches, setDevicePatches] = useState<PatchDetail[]>([]);
  const [patchLoading, setPatchLoading] = useState(false);
  const [drillView, setDrillView] = useState<"packages" | "advisories">("advisories");

  useEffect(() => {
    Promise.all([
      api.get("/patches/compliance"),
      api.get("/patches/by-cve"),
    ]).then(([d, c]) => {
      setDevices(d.data);
      setCves(c.data);
    }).finally(() => setLoading(false));
  }, []);

  function toggleType(t: string) {
    setTypeFilter(prev => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });
  }

  async function openDevice(d: DeviceRow) {
    setSelectedDevice(d);
    setPatchLoading(true);
    try {
      const res = await api.get(`/patches/by-device/${d.minion_id}`);
      setDevicePatches(res.data);
    } finally {
      setPatchLoading(false);
    }
  }

  async function scanAll() {
    await api.post("/minions/patches/scan-all");
    window.location.reload();
  }

  const activeTypeFilters = [...typeFilter];
  const filteredCves = cves.filter(c => {
    if (severityFilter !== "all" && c.severity !== severityFilter) return false;
    if (activeTypeFilters.length > 0 && !activeTypeFilters.includes(c.advisory_type)) return false;
    return true;
  });
  const filteredDevicePatches = devicePatches.filter(p =>
    activeTypeFilters.length === 0 || activeTypeFilters.includes(p.advisory_type)
  );

  const severities = ["all", ...Array.from(new Set(cves.map(c => c.severity))).sort()];

  const totalDevices = devices.length;
  const totalAdvisories = cves.length;
  const criticalCount = devices.reduce((s, d) => s + d.critical, 0);
  const fullyPatched = devices.filter(d => d.total_patches === 0).length;
  const pctPatched = totalDevices ? Math.round((fullyPatched / totalDevices) * 100) : 0;

  // group devices by OS
  const windowsDevices = devices.filter(d => d.os_family === "windows");
  const linuxDevices   = devices.filter(d => d.os_family === "linux");
  const otherDevices   = devices.filter(d => d.os_family === "unknown");

  function DeviceTableRows({ rows }: { rows: DeviceRow[] }) {
    return (
      <>
        {[...rows].sort((a, b) => b.total_patches - a.total_patches).map(d => (
          <tr
            key={d.minion_id}
            onClick={() => openDevice(d)}
            className={`border-t border-border hover:bg-muted/40 cursor-pointer transition-colors ${selectedDevice?.minion_id === d.minion_id ? "bg-primary/10" : ""}`}
          >
            <td className="px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="text-base" title={d.os_family}>{OS_ICON[d.os_family] ?? "?"}</span>
                <div>
                  <div className="font-medium text-foreground">{d.hostname}</div>
                  <div className="text-xs text-muted-foreground font-mono">{d.minion_id.slice(0, 8)}…</div>
                </div>
              </div>
            </td>
            <td className="px-4 py-3">
              {d.critical > 0 ? <span className={`px-2 py-0.5 rounded border text-xs ${SEVERITY_BADGE.critical}`}>{d.critical}</span> : <span className="text-muted-foreground">—</span>}
            </td>
            <td className="px-4 py-3">
              {d.high > 0 ? <span className={`px-2 py-0.5 rounded border text-xs ${SEVERITY_BADGE.high}`}>{d.high}</span> : <span className="text-muted-foreground">—</span>}
            </td>
            <td className="px-4 py-3">
              {d.total_patches > 0
                ? <span className="font-medium text-foreground">{d.total_patches}</span>
                : <span className="text-green-400 text-xs">✓ clean</span>}
            </td>
            <td className="px-4 py-3 text-muted-foreground text-xs">
              {d.last_scanned ? new Date(d.last_scanned).toLocaleString() : <span className="text-yellow-500">never scanned</span>}
            </td>
          </tr>
        ))}
      </>
    );
  }

  function OsGroup({ label, icon, rows }: { label: string; icon: string; rows: DeviceRow[] }) {
    if (rows.length === 0) return null;
    return (
      <>
        <tr className="bg-muted/60">
          <td colSpan={5} className="px-4 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            {icon} {label} <span className="ml-1 opacity-60">({rows.length})</span>
          </td>
        </tr>
        <DeviceTableRows rows={rows} />
      </>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Patch Compliance</h1>
          <p className="text-muted-foreground text-sm mt-1">Fleet-wide patch state</p>
        </div>
        <button onClick={scanAll} className="px-3 py-1.5 border border-border rounded-lg text-sm text-muted-foreground hover:text-foreground">
          ↻ Scan All
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: "Total Devices", value: totalDevices },
          { label: "Total Advisories", value: totalAdvisories },
          { label: "Critical Patches", value: criticalCount, danger: criticalCount > 0 },
          { label: "% Fully Patched", value: `${pctPatched}%` },
        ].map(c => (
          <div key={c.label} className="bg-card border border-border rounded-lg p-4">
            <p className="text-xs text-muted-foreground uppercase">{c.label}</p>
            <p className={`text-3xl font-bold mt-1 ${c.danger ? "text-red-400" : "text-foreground"}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4">
        {(["device", "cve"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${tab === t ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>
            {t === "device" ? "By Device" : "By Patch / CVE"}
          </button>
        ))}
      </div>

      {/* Global advisory type filter — shown on both tabs */}
      {!loading && (
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <span className="text-xs text-muted-foreground uppercase font-semibold flex items-center gap-1">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M3 4h18M7 8h10M11 12h2M9 16h6"/></svg>
            Filter
          </span>
          {ADVISORY_TYPES.map(t => (
            <label key={t} className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={typeFilter.has(t)}
                onChange={() => toggleType(t)}
                className="rounded border-border accent-primary"
              />
              <span className={`text-xs font-medium ${typeFilter.has(t) ? "text-foreground" : "text-muted-foreground"}`}>
                {TYPE_LABEL[t]}
              </span>
            </label>
          ))}
          {typeFilter.size > 0 && (
            <button onClick={() => setTypeFilter(new Set())} className="text-xs text-muted-foreground hover:text-foreground underline ml-1">
              Clear
            </button>
          )}
        </div>
      )}

      {loading ? <p className="text-muted-foreground">Loading…</p> : tab === "device" ? (
        <div className={`flex gap-4 ${selectedDevice ? "items-start" : ""}`}>
          {/* Device table */}
          <div className={`rounded-lg border border-border overflow-hidden ${selectedDevice ? "flex-1" : "w-full"}`}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 sticky top-0 z-10">
                  <tr className="text-muted-foreground text-xs uppercase">
                    <th className="px-4 py-3 text-left">Host</th>
                    <th className="px-4 py-3 text-left">Critical</th>
                    <th className="px-4 py-3 text-left">High</th>
                    <th className="px-4 py-3 text-left">Advisories</th>
                    <th className="px-4 py-3 text-left">Last Scan</th>
                  </tr>
                </thead>
                <tbody>
                  {devices.length === 0 ? (
                    <tr><td colSpan={5} className="px-4 py-8 text-center text-muted-foreground text-sm">No devices found.</td></tr>
                  ) : (
                    <>
                      <OsGroup label="Windows" icon="⊞" rows={windowsDevices} />
                      <OsGroup label="Linux"   icon="🐧" rows={linuxDevices} />
                      <OsGroup label="Unknown" icon="?" rows={otherDevices} />
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Drill-down panel */}
          {selectedDevice && (
            <div className="w-[480px] shrink-0 rounded-lg border border-border bg-card overflow-hidden flex flex-col max-h-[80vh] sticky top-6">
              {/* Panel header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/40">
                <div className="flex items-center gap-2 font-semibold text-foreground">
                  <span>{OS_ICON[selectedDevice.os_family]}</span>
                  {selectedDevice.hostname}
                </div>
                <div className="flex items-center gap-2">
                  {/* Packages / Advisories toggle */}
                  <div className="flex rounded-lg border border-border overflow-hidden text-xs">
                    {(["advisories", "packages"] as const).map(v => (
                      <button key={v} onClick={() => setDrillView(v)}
                        className={`px-2.5 py-1 capitalize transition-colors ${drillView === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>
                        {v}
                      </button>
                    ))}
                  </div>
                  <button onClick={() => setSelectedDevice(null)} className="text-muted-foreground hover:text-foreground text-lg leading-none ml-1">✕</button>
                </div>
              </div>

              <div className="overflow-y-auto flex-1">
                {patchLoading ? (
                  <p className="px-4 py-6 text-muted-foreground text-sm">Loading patches…</p>
                ) : filteredDevicePatches.length === 0 ? (
                  <p className="px-4 py-6 text-center text-muted-foreground text-sm">
                    {devicePatches.length === 0 ? "✓ No patches needed — device is clean." : "No patches match the current filter."}
                  </p>
                ) : drillView === "packages" ? (
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50 sticky top-0">
                      <tr className="text-muted-foreground text-xs uppercase">
                        <th className="px-3 py-2 text-left">Package</th>
                        <th className="px-3 py-2 text-left">Severity</th>
                        <th className="px-3 py-2 text-left">Type</th>
                        <th className="px-3 py-2 text-left">Version</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredDevicePatches.map((p, i) => (
                        <tr key={i} className="border-t border-border hover:bg-muted/30">
                          <td className="px-3 py-2">
                            <div className="font-medium text-foreground text-xs">{p.package_name}</div>
                            {p.cve_ids.length > 0 && (
                              <div className="text-xs text-muted-foreground font-mono mt-0.5">{p.cve_ids.slice(0, 2).join(", ")}{p.cve_ids.length > 2 ? ` +${p.cve_ids.length - 2}` : ""}</div>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <span className={`px-1.5 py-0.5 rounded border text-xs ${SEVERITY_BADGE[p.severity] ?? SEVERITY_BADGE.none}`}>{p.severity}</span>
                          </td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">{TYPE_LABEL[p.advisory_type] ?? p.advisory_type}</td>
                          <td className="px-3 py-2 text-xs text-muted-foreground font-mono">
                            {p.installed_version && <span>{p.installed_version} → </span>}
                            <span className="text-foreground">{p.available_version}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  /* Advisories view — group packages by advisory_id */
                  (() => {
                    const groups = new Map<string, PatchDetail[]>();
                    filteredDevicePatches.forEach(p => {
                      const key = p.advisory_id || `${p.package_name}-${p.available_version}`;
                      if (!groups.has(key)) groups.set(key, []);
                      groups.get(key)!.push(p);
                    });
                    return (
                      <table className="w-full text-sm">
                        <thead className="bg-muted/50 sticky top-0">
                          <tr className="text-muted-foreground text-xs uppercase">
                            <th className="px-3 py-2 text-left">Advisory</th>
                            <th className="px-3 py-2 text-left">Severity</th>
                            <th className="px-3 py-2 text-left">Type</th>
                            <th className="px-3 py-2 text-left">Packages</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...groups.entries()].map(([key, pkgs]) => (
                            <tr key={key} className="border-t border-border hover:bg-muted/30">
                              <td className="px-3 py-2">
                                <div className="font-medium text-foreground text-xs font-mono">{pkgs[0].advisory_id || pkgs[0].package_name}</div>
                                {pkgs[0].cve_ids.length > 0 && (
                                  <div className="text-xs text-muted-foreground font-mono mt-0.5">{pkgs[0].cve_ids.slice(0, 2).join(", ")}</div>
                                )}
                              </td>
                              <td className="px-3 py-2">
                                <span className={`px-1.5 py-0.5 rounded border text-xs ${SEVERITY_BADGE[pkgs[0].severity] ?? SEVERITY_BADGE.none}`}>{pkgs[0].severity}</span>
                              </td>
                              <td className="px-3 py-2 text-xs text-muted-foreground">{TYPE_LABEL[pkgs[0].advisory_type] ?? pkgs[0].advisory_type}</td>
                              <td className="px-3 py-2 text-xs text-muted-foreground">
                                {pkgs.length === 1 ? pkgs[0].package_name : (
                                  <span>{pkgs[0].package_name} <span className="text-muted-foreground/60">+{pkgs.length - 1} more</span></span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    );
                  })()
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        /* CVE tab */
        <>
          {/* Severity filter for CVE tab */}
          <div className="flex flex-wrap gap-4 mb-4 items-center">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground uppercase font-semibold">Severity</span>
              <div className="flex gap-1">
                {severities.map(s => (
                  <button key={s} onClick={() => setSeverityFilter(s)}
                    className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                      severityFilter === s
                        ? s === "all" ? "bg-primary text-primary-foreground border-primary" : `${SEVERITY_BADGE[s] ?? SEVERITY_BADGE.none} border-current`
                        : "bg-muted text-muted-foreground border-border hover:text-foreground"
                    }`}>
                    {s === "all" ? "All" : s}
                    {s !== "all" && <span className="ml-1 opacity-60">({cves.filter(c => c.severity === s).length})</span>}
                  </button>
                ))}
              </div>
            </div>
            {(severityFilter !== "all" || typeFilter.size > 0) && (
              <button onClick={() => { setSeverityFilter("all"); setTypeFilter(new Set()); }} className="text-xs text-muted-foreground hover:text-foreground underline">
                Clear all filters
              </button>
            )}
            <span className="text-xs text-muted-foreground ml-auto">{filteredCves.length} / {cves.length} advisories</span>
          </div>

          <div className="rounded-lg border border-border overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 sticky top-0 z-10">
                  <tr className="text-muted-foreground text-xs uppercase">
                    <th className="px-4 py-3 text-left">Advisory / Package</th>
                    <th className="px-4 py-3 text-left">Severity</th>
                    <th className="px-4 py-3 text-left">Type</th>
                    <th className="px-4 py-3 text-left">CVEs</th>
                    <th className="px-4 py-3 text-left">Affected</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCves.length === 0 ? (
                    <tr><td colSpan={5} className="px-4 py-8 text-center text-muted-foreground text-sm">No advisories match the current filters.</td></tr>
                  ) : (
                    filteredCves.map((c, i) => (
                      <tr key={i} className="border-t border-border hover:bg-muted/30">
                        <td className="px-4 py-3">
                          <div className="font-medium">{c.advisory_id || c.package_name}</div>
                          {c.advisory_id && <div className="text-xs text-muted-foreground">{c.package_name}</div>}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded border text-xs ${SEVERITY_BADGE[c.severity] ?? SEVERITY_BADGE.none}`}>{c.severity}</span>
                        </td>
                        <td className="px-4 py-3 text-muted-foreground text-xs">{TYPE_LABEL[c.advisory_type] ?? c.advisory_type}</td>
                        <td className="px-4 py-3 text-xs font-mono text-muted-foreground">
                          {c.cve_ids.slice(0, 2).join(", ")}{c.cve_ids.length > 2 ? ` +${c.cve_ids.length - 2}` : ""}
                          {c.cve_ids.length === 0 && "—"}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">{c.affected_minion_ids.length}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
