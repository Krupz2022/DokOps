import { useEffect, useState } from "react";
import { ShieldCheck, RefreshCw, X, AppWindow, Terminal, HelpCircle, SlidersHorizontal, type LucideIcon } from "lucide-react";
import api from "../lib/api";
import { Button } from "../components/ui/Button";
import { cn } from "../lib/utils";
import { FleetPage, FleetStat, Surface, Eyebrow } from "../components/fleet/FleetPage";

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

/* Theme-aligned severity chips (replaces the old heavy bg-*-900 palette). */
const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-red-500/10 text-red-400 border-red-500/25",
  high:     "bg-orange-500/10 text-orange-400 border-orange-500/25",
  medium:   "bg-amber-500/10 text-amber-400 border-amber-500/25",
  low:      "bg-sky-500/10 text-sky-400 border-sky-500/25",
  none:     "bg-secondary text-muted-foreground border-border",
};

function Severity({ value }: { value: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-sm border px-1.5 py-0.5 font-mono text-[11px] font-medium", SEVERITY_BADGE[value] ?? SEVERITY_BADGE.none)}>
      {value}
    </span>
  );
}

const TYPE_LABEL: Record<string, string> = {
  security: "Security",
  bugfix: "Bug Fix",
  enhancement: "Enhancement",
};

const OS_META: Record<string, { label: string; Icon: LucideIcon }> = {
  windows: { label: "Windows", Icon: AppWindow },
  linux:   { label: "Linux", Icon: Terminal },
  unknown: { label: "Unknown", Icon: HelpCircle },
};

const ADVISORY_TYPES = ["security", "bugfix", "enhancement"] as const;

export default function Patching() {
  const [tab, setTab] = useState<"device" | "cve">("device");
  const [devices, setDevices] = useState<DeviceRow[]>([]);
  const [cves, setCves] = useState<CveRow[]>([]);
  const [loading, setLoading] = useState(true);

  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [severityFilter, setSeverityFilter] = useState<string>("all");

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
            className={cn(
              "border-t border-border/70 hover:bg-secondary/40 cursor-pointer transition-colors",
              selectedDevice?.minion_id === d.minion_id && "bg-primary/10",
            )}
          >
            <td className="px-4 py-3">
              <div className="font-medium text-foreground">{d.hostname}</div>
              <div className="text-[11px] text-muted-foreground font-mono">{d.minion_id.slice(0, 8)}…</div>
            </td>
            <td className="px-4 py-3">
              {d.critical > 0 ? <Severity value="critical" /> : <span className="text-muted-foreground">—</span>}
            </td>
            <td className="px-4 py-3">
              {d.high > 0 ? <Severity value="high" /> : <span className="text-muted-foreground">—</span>}
            </td>
            <td className="px-4 py-3">
              {d.total_patches > 0
                ? <span className="font-medium text-foreground">{d.total_patches}</span>
                : <span className="text-emerald-400 text-xs font-medium">clean</span>}
            </td>
            <td className="px-4 py-3 text-muted-foreground text-xs font-mono">
              {d.last_scanned ? new Date(d.last_scanned).toLocaleString() : <span className="text-amber-400">never scanned</span>}
            </td>
          </tr>
        ))}
      </>
    );
  }

  function OsGroup({ os, rows }: { os: string; rows: DeviceRow[] }) {
    if (rows.length === 0) return null;
    const { label, Icon } = OS_META[os] ?? OS_META.unknown;
    return (
      <>
        <tr className="bg-secondary/50">
          <td colSpan={5} className="px-4 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            <span className="inline-flex items-center gap-1.5"><Icon className="w-3.5 h-3.5" /> {label} <span className="opacity-60">({rows.length})</span></span>
          </td>
        </tr>
        <DeviceTableRows rows={rows} />
      </>
    );
  }

  const TH = "px-4 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground";
  const headerRow = "border-b border-border dark:[border-bottom-color:hsl(191_89%_55%_/_0.07)]";

  return (
    <FleetPage
      icon={ShieldCheck}
      title="Compliance"
      subtitle="Fleet-wide patch state — outstanding advisories by device and by CVE."
      vitals={
        <>
          <FleetStat value={totalDevices} label="devices" tone="cyan" />
          <FleetStat value={totalAdvisories} label="advisories" tone="blue" />
          <FleetStat value={criticalCount} label="critical" tone={criticalCount > 0 ? "red" : "slate"} />
          <FleetStat value={`${pctPatched}%`} label="patched" tone="green" />
        </>
      }
      actions={<Button variant="outline" size="sm" onClick={scanAll}><RefreshCw className="w-3.5 h-3.5" /> Scan all</Button>}
    >
      {/* Tabs */}
      <div className="inline-flex p-1 rounded-lg bg-secondary/50 border border-border mb-4">
        {(["device", "cve"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={cn(
              "px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors",
              tab === t ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}>
            {t === "device" ? "By device" : "By patch / CVE"}
          </button>
        ))}
      </div>

      {/* Global advisory type filter */}
      {!loading && (
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider text-muted-foreground/70">
            <SlidersHorizontal className="w-3.5 h-3.5" /> Filter
          </span>
          {ADVISORY_TYPES.map(t => (
            <label key={t} className="flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" checked={typeFilter.has(t)} onChange={() => toggleType(t)} className="rounded border-border accent-primary" />
              <span className={cn("text-xs font-medium", typeFilter.has(t) ? "text-foreground" : "text-muted-foreground")}>{TYPE_LABEL[t]}</span>
            </label>
          ))}
          {typeFilter.size > 0 && (
            <button onClick={() => setTypeFilter(new Set())} className="text-xs text-muted-foreground hover:text-foreground underline ml-1">Clear</button>
          )}
        </div>
      )}

      {loading ? <p className="text-muted-foreground text-sm">Loading…</p> : tab === "device" ? (
        <div className="flex gap-4 items-start">
          {/* Device table */}
          <Surface className={cn("overflow-hidden", selectedDevice ? "flex-1 min-w-0" : "w-full")}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className={headerRow}>
                    <th className={TH}>Host</th>
                    <th className={TH}>Critical</th>
                    <th className={TH}>High</th>
                    <th className={TH}>Advisories</th>
                    <th className={TH}>Last scan</th>
                  </tr>
                </thead>
                <tbody>
                  {devices.length === 0 ? (
                    <tr><td colSpan={5} className="px-4 py-10 text-center text-muted-foreground text-sm">No devices found.</td></tr>
                  ) : (
                    <>
                      <OsGroup os="windows" rows={windowsDevices} />
                      <OsGroup os="linux" rows={linuxDevices} />
                      <OsGroup os="unknown" rows={otherDevices} />
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </Surface>

          {/* Drill-down panel */}
          {selectedDevice && (
            <Surface className="w-[480px] shrink-0 overflow-hidden flex flex-col max-h-[80vh] sticky top-6">
              <div className="flex items-center justify-between px-4 py-3 border-b border-border/70 bg-secondary/40">
                <div className="flex items-center gap-2 font-semibold text-foreground">
                  {(() => { const { Icon } = OS_META[selectedDevice.os_family] ?? OS_META.unknown; return <Icon className="w-4 h-4 text-muted-foreground" />; })()}
                  {selectedDevice.hostname}
                </div>
                <div className="flex items-center gap-2">
                  <div className="inline-flex rounded-lg border border-border overflow-hidden text-xs">
                    {(["advisories", "packages"] as const).map(v => (
                      <button key={v} onClick={() => setDrillView(v)}
                        className={cn("px-2.5 py-1 capitalize transition-colors", drillView === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                        {v}
                      </button>
                    ))}
                  </div>
                  <button onClick={() => setSelectedDevice(null)} title="Close"
                    className="inline-flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="overflow-y-auto flex-1">
                {patchLoading ? (
                  <p className="px-4 py-6 text-muted-foreground text-sm">Loading patches…</p>
                ) : filteredDevicePatches.length === 0 ? (
                  <p className="px-4 py-6 text-center text-muted-foreground text-sm">
                    {devicePatches.length === 0 ? "No patches needed — device is clean." : "No patches match the current filter."}
                  </p>
                ) : drillView === "packages" ? (
                  <table className="w-full text-sm">
                    <thead className="bg-secondary/40 sticky top-0">
                      <tr>
                        <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Package</th>
                        <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Severity</th>
                        <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Type</th>
                        <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Version</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredDevicePatches.map((p, i) => (
                        <tr key={i} className="border-t border-border/70 hover:bg-secondary/40">
                          <td className="px-3 py-2">
                            <div className="font-medium text-foreground text-xs">{p.package_name}</div>
                            {p.cve_ids.length > 0 && (
                              <div className="text-[11px] text-muted-foreground font-mono mt-0.5">{p.cve_ids.slice(0, 2).join(", ")}{p.cve_ids.length > 2 ? ` +${p.cve_ids.length - 2}` : ""}</div>
                            )}
                          </td>
                          <td className="px-3 py-2"><Severity value={p.severity} /></td>
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
                  (() => {
                    const groups = new Map<string, PatchDetail[]>();
                    filteredDevicePatches.forEach(p => {
                      const key = p.advisory_id || `${p.package_name}-${p.available_version}`;
                      if (!groups.has(key)) groups.set(key, []);
                      groups.get(key)!.push(p);
                    });
                    return (
                      <table className="w-full text-sm">
                        <thead className="bg-secondary/40 sticky top-0">
                          <tr>
                            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Advisory</th>
                            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Severity</th>
                            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Type</th>
                            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Packages</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...groups.entries()].map(([key, pkgs]) => (
                            <tr key={key} className="border-t border-border/70 hover:bg-secondary/40">
                              <td className="px-3 py-2">
                                <div className="font-medium text-foreground text-xs font-mono">{pkgs[0].advisory_id || pkgs[0].package_name}</div>
                                {pkgs[0].cve_ids.length > 0 && (
                                  <div className="text-[11px] text-muted-foreground font-mono mt-0.5">{pkgs[0].cve_ids.slice(0, 2).join(", ")}</div>
                                )}
                              </td>
                              <td className="px-3 py-2"><Severity value={pkgs[0].severity} /></td>
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
            </Surface>
          )}
        </div>
      ) : (
        <>
          {/* Severity filter for CVE tab */}
          <div className="flex flex-wrap gap-4 mb-4 items-center">
            <div className="flex items-center gap-2">
              <Eyebrow>Severity</Eyebrow>
              <div className="flex gap-1">
                {severities.map(s => (
                  <button key={s} onClick={() => setSeverityFilter(s)}
                    className={cn(
                      "px-2.5 py-1 rounded-md text-xs font-medium border transition-colors",
                      severityFilter === s
                        ? s === "all" ? "bg-primary text-primary-foreground border-primary" : cn(SEVERITY_BADGE[s] ?? SEVERITY_BADGE.none, "border-current")
                        : "bg-secondary/50 text-muted-foreground border-border hover:text-foreground",
                    )}>
                    {s === "all" ? "All" : s}
                    {s !== "all" && <span className="ml-1 opacity-60">({cves.filter(c => c.severity === s).length})</span>}
                  </button>
                ))}
              </div>
            </div>
            {(severityFilter !== "all" || typeFilter.size > 0) && (
              <button onClick={() => { setSeverityFilter("all"); setTypeFilter(new Set()); }} className="text-xs text-muted-foreground hover:text-foreground underline">Clear all filters</button>
            )}
            <span className="text-xs text-muted-foreground ml-auto">{filteredCves.length} / {cves.length} advisories</span>
          </div>

          <Surface className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className={headerRow}>
                    <th className={TH}>Advisory / Package</th>
                    <th className={TH}>Severity</th>
                    <th className={TH}>Type</th>
                    <th className={TH}>CVEs</th>
                    <th className={TH}>Affected</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCves.length === 0 ? (
                    <tr><td colSpan={5} className="px-4 py-10 text-center text-muted-foreground text-sm">No advisories match the current filters.</td></tr>
                  ) : (
                    filteredCves.map((c, i) => (
                      <tr key={i} className="border-t border-border/70 hover:bg-secondary/40">
                        <td className="px-4 py-3">
                          <div className="font-medium text-foreground">{c.advisory_id || c.package_name}</div>
                          {c.advisory_id && <div className="text-xs text-muted-foreground">{c.package_name}</div>}
                        </td>
                        <td className="px-4 py-3"><Severity value={c.severity} /></td>
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
          </Surface>
        </>
      )}
    </FleetPage>
  );
}
