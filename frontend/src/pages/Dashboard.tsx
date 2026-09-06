import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  api,
  ApiError,
  type AiBriefing,
  type AskResult,
  type ContributionResult,
  type UrgencyLevel,
  type ZoneGap,
} from "../lib/api";
import { useDashboard } from "../hooks/useDashboard";
import { Combobox } from "../components/Combobox";
import { CountUp } from "../components/CountUp";
import {
  SkeletonChart,
  SkeletonStatCard,
  SkeletonTable,
  SkeletonText,
} from "../components/Skeleton";
import "./Dashboard.css";

const CLUSTER = (import.meta.env.VITE_SOLANA_CLUSTER as string) || "devnet";

const number = (value: number) => new Intl.NumberFormat("en-US").format(Math.round(value));

const EMPTY_MSG = "No data yet — submit a contribution above to populate this.";
const EmptyState = () => <p className="empty-state">{EMPTY_MSG}</p>;

const explorerUrl = (sig: string) => `https://explorer.solana.com/tx/${sig}?cluster=${CLUSTER}`;

const URGENCY_LABEL: Record<UrgencyLevel, string> = {
  critical: "Critical",
  medium: "Medium",
  low: "Low",
};

const URGENCY_RANK: Record<UrgencyLevel, number> = { critical: 3, medium: 2, low: 1 };

const URGENCY_FILL: Record<UrgencyLevel, string> = {
  critical: "#9c2b26",
  medium: "#b9832a",
  low: "#2f6f62",
};

interface ZoneUrgencyRow {
  zone_name: string;
  unmet_pct: number; // worst (highest) % of need unmet across the zone's resources
  urgency_level: UrgencyLevel;
}

const pctUnmet = (g: ZoneGap) =>
  g.quantity_needed > 0 ? (100 * Math.max(0, g.unmet_need)) / g.quantity_needed : 0;

// One bar per zone: the worst unmet % among its resources (units differ per
// resource, so a percentage is the only honest way to compare zones), coloured
// by that zone's worst urgency.
function toZoneUrgency(gaps: ZoneGap[]): ZoneUrgencyRow[] {
  const byZone = new Map<string, ZoneUrgencyRow>();
  for (const g of gaps) {
    const prev = byZone.get(g.zone_name);
    const worst =
      prev && URGENCY_RANK[prev.urgency_level] >= URGENCY_RANK[g.urgency_level]
        ? prev.urgency_level
        : g.urgency_level;
    byZone.set(g.zone_name, {
      zone_name: g.zone_name,
      unmet_pct: Math.max(prev?.unmet_pct ?? 0, pctUnmet(g)),
      urgency_level: worst,
    });
  }
  return [...byZone.values()].sort((a, b) => b.unmet_pct - a.unmet_pct);
}

export function Dashboard() {
  const {
    zoneGaps,
    resourceBreakdown,
    responseTrend,
    recentDeliveries,
    loading,
    error,
    live,
    stats,
    reload: loadDashboard,
  } = useDashboard();

  const [briefing, setBriefing] = useState<AiBriefing | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingError, setBriefingError] = useState<string | null>(null);

  const [askQuestion, setAskQuestion] = useState("");
  const [askResult, setAskResult] = useState<AskResult | null>(null);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  const [zones, setZones] = useState<string[]>([]);
  const [resourceOptions, setResourceOptions] = useState<string[]>([]);
  const [form, setForm] = useState({
    donor_org: "",
    donor_email: "",
    cause_note: "",
    resource_type: "",
    quantity: "",
    zone_name: "",
    website: "", // honeypot
  });
  const [pdfLoading, setPdfLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<ContributionResult | null>(null);

  useEffect(() => {
    Promise.all([api.zones(), api.resourceTypes()])
      .then(([z, r]) => {
        setZones(z);
        setResourceOptions(r);
        setForm((f) => ({
          ...f,
          resource_type: f.resource_type || r[0] || "",
          zone_name: f.zone_name || z[0] || "",
        }));
      })
      .catch(() => {
        /* form falls back to a free-text zone if the lists can't load */
      });
  }, []);

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.donor_email.trim());

  const canSubmit =
    form.donor_org.trim() !== "" &&
    emailValid &&
    form.resource_type !== "" &&
    form.zone_name.trim() !== "" &&
    Number(form.quantity) > 0 &&
    !submitting;

  const submitContribution = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    setConfirmation(null);
    try {
      const result = await api.contribute({
        donor_org: form.donor_org.trim(),
        donor_email: form.donor_email.trim(),
        cause_note: form.cause_note.trim(),
        resource_type: form.resource_type,
        quantity: Number(form.quantity),
        zone_name: form.zone_name.trim(),
        website: form.website,
      });
      setConfirmation(result);
      setForm((f) => ({ ...f, donor_org: "", donor_email: "", cause_note: "", quantity: "" }));
      loadDashboard();
    } catch (err) {
      setSubmitError(
        err instanceof ApiError ? err.message : "Something went wrong submitting your contribution.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const generateBriefing = async () => {
    setBriefingLoading(true);
    setBriefingError(null);
    try {
      setBriefing(await api.aiBriefing());
    } catch (err) {
      setBriefingError(err instanceof ApiError ? err.message : "Could not generate briefing.");
    } finally {
      setBriefingLoading(false);
    }
  };

  const downloadPdf = async () => {
    setPdfLoading(true);
    setBriefingError(null);
    try {
      const blob = await api.briefingPdf();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "relieftrace-briefing.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setBriefingError(err instanceof ApiError ? err.message : "Could not build the PDF.");
    } finally {
      setPdfLoading(false);
    }
  };

  const runAsk = async (e: FormEvent) => {
    e.preventDefault();
    const q = askQuestion.trim();
    if (q.length < 3 || askLoading) return;
    setAskLoading(true);
    setAskError(null);
    try {
      setAskResult(await api.ask(q));
    } catch (err) {
      setAskError(err instanceof ApiError ? err.message : "Could not answer that.");
    } finally {
      setAskLoading(false);
    }
  };

  const ASK_SAMPLES = [
    "Which district has the worst medical shortage?",
    "How many people are affected in total?",
    "Which Punjab districts still have critical water gaps?",
  ];

  const { peopleAffected, criticalZones, verifiedDeliveries } = stats;

  // Units differ per resource, so plot coverage as a percentage of need met.
  const resourceCoverage = resourceBreakdown.map((r) => ({
    resource_type: r.resource_type,
    unit: r.unit,
    fulfilled_pct: r.total_needed > 0 ? (100 * r.total_fulfilled) / r.total_needed : 0,
    unmet_pct: r.total_needed > 0 ? (100 * Math.max(0, r.unmet_need)) / r.total_needed : 0,
  }));
  const zoneUrgency = toZoneUrgency(zoneGaps);

  // --- Zone Resource Gaps: client-side urgency filter + column sort ---------
  type GapSortKey =
    | "zone_name"
    | "resource_type"
    | "quantity_needed"
    | "quantity_fulfilled"
    | "unmet_need"
    | "urgency_level";
  const [gapUrgency, setGapUrgency] = useState<"all" | UrgencyLevel>("all");
  const [gapSort, setGapSort] = useState<{ key: GapSortKey; dir: "asc" | "desc" }>({
    key: "unmet_need",
    dir: "desc",
  });

  const toggleGapSort = (key: GapSortKey) =>
    setGapSort((s) =>
      s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );

  const urgencyCounts = useMemo(() => {
    const c = { all: zoneGaps.length, critical: 0, medium: 0, low: 0 };
    for (const g of zoneGaps) c[g.urgency_level] += 1;
    return c;
  }, [zoneGaps]);

  const visibleGaps = useMemo(() => {
    const rows = zoneGaps.filter((g) => gapUrgency === "all" || g.urgency_level === gapUrgency);
    const { key, dir } = gapSort;
    const mul = dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      if (key === "zone_name" || key === "resource_type") {
        av = a[key];
        bv = b[key];
      } else if (key === "urgency_level") {
        av = URGENCY_RANK[a.urgency_level];
        bv = URGENCY_RANK[b.urgency_level];
      } else {
        av = a[key];
        bv = b[key];
      }
      if (av < bv) return -1 * mul;
      if (av > bv) return 1 * mul;
      return 0;
    });
  }, [zoneGaps, gapUrgency, gapSort]);

  const sortArrow = (key: GapSortKey) =>
    gapSort.key === key ? (gapSort.dir === "asc" ? " ▲" : " ▼") : "";

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div>
          <span className="brand-eyebrow">ReliefTrace</span>
          <h1>Aid you can actually verify.</h1>
          <p>
            Log a relief contribution and watch it get recorded on a public blockchain, then see
            district needs and an AI situation briefing. Need estimates are calculated from real
            affected-population data (2024 Assam floods, 2025 Punjab floods) using Sphere Handbook
            humanitarian minimum standards — not live operational feeds, since granular real-time
            need data isn&rsquo;t publicly available at this resolution.
          </p>
        </div>
        <div className="header-actions">
          <span className={`live-indicator live-${live}`} title={`Live updates: ${live}`}>
            <span className="live-dot" />
            {live === "open" ? "Live" : live === "connecting" ? "Connecting…" : "Offline"}
          </span>
          <button className="btn-refresh" onClick={loadDashboard} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <section className="panel panel-wide contribute-panel">
        <h2>Log a Contribution</h2>
        <p className="table-hint">
          Every submission is written to Snowflake and anchored with a Solana devnet memo
          transaction. No account, no payment.
        </p>
        <form className="contribute-form" onSubmit={submitContribution}>
          {/* Honeypot: hidden from real users, tempting to bots. If it comes
              back filled, the backend rejects the submission. */}
          <div className="hp-field" aria-hidden="true">
            <label htmlFor="website">Website</label>
            <input
              id="website"
              type="text"
              tabIndex={-1}
              autoComplete="off"
              value={form.website}
              onChange={(e) => setForm({ ...form, website: e.target.value })}
            />
          </div>
          <label>
            <span>Organization or name</span>
            <input
              type="text"
              value={form.donor_org}
              onChange={(e) => setForm({ ...form, donor_org: e.target.value })}
              placeholder="e.g. Riverside Mutual Aid"
              maxLength={80}
              required
            />
          </label>
          <label>
            <span>Email</span>
            <input
              type="email"
              value={form.donor_email}
              onChange={(e) => setForm({ ...form, donor_email: e.target.value })}
              placeholder="you@example.org"
              maxLength={120}
              required
            />
          </label>
          <label className="field-wide">
            <span>Note (optional)</span>
            <input
              type="text"
              value={form.cause_note}
              onChange={(e) => setForm({ ...form, cause_note: e.target.value })}
              placeholder="e.g. Assam flood relief drive — via local Rotary chapter"
              maxLength={140}
            />
          </label>
          <label>
            <span>Resource type</span>
            <select
              value={form.resource_type}
              onChange={(e) => setForm({ ...form, resource_type: e.target.value })}
              required
            >
              {resourceOptions.length === 0 && <option value="">Loading…</option>}
              {resourceOptions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Quantity</span>
            <input
              type="number"
              min="1"
              step="1"
              value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              placeholder="e.g. 500"
              required
            />
          </label>
          <label>
            <span>Zone</span>
            <Combobox
              value={form.zone_name}
              onChange={(v) => setForm((f) => ({ ...f, zone_name: v }))}
              options={zones}
              placeholder="Type to filter zones…"
              maxLength={80}
              required
            />
          </label>
          <button type="submit" className="btn-submit" disabled={!canSubmit}>
            {submitting ? "Recording on-chain…" : "Submit contribution"}
          </button>
        </form>

        {submitError && <p className="upload-error">{submitError}</p>}

        {confirmation && (
          <div className="confirmation">
            <p className="confirmation-headline">Recorded and verified</p>
            <p className="confirmation-detail">
              {number(confirmation.quantity)} {confirmation.resource_type} for{" "}
              {confirmation.zone_name}, from {confirmation.donor_org} ({confirmation.donor_email}).
              {confirmation.cause_note && ` — ${confirmation.cause_note}`}
            </p>
            <a
              className="verify-link"
              href={confirmation.explorer_url}
              target="_blank"
              rel="noreferrer"
            >
              View on-chain ↗
            </a>
            {confirmation.receipt_email && (
              <p className="confirmation-email">
                A receipt is on its way to {confirmation.donor_email}.
              </p>
            )}
          </div>
        )}
      </section>

      {error && (
        <p className="error-banner">
          Couldn't reach the API ({error}). Is the FastAPI backend running on port 8000?
        </p>
      )}

      <section className="stat-row">
        {loading ? (
          <>
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
          </>
        ) : (
          <>
            <div className="stat-card">
              <span className="stat-label">People Affected</span>
              <span className="stat-value">
                <CountUp value={peopleAffected} />
              </span>
              <span className="stat-sub">across 15 districts — 2024 Assam &amp; 2025 Punjab floods</span>
            </div>
            <div className="stat-card stat-card-critical">
              <span className="stat-label">Districts with Critical Gaps</span>
              <span className="stat-value">
                <CountUp value={criticalZones} />
              </span>
              <span className="stat-sub">&ge;66% of estimated need unmet</span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Verified Deliveries</span>
              <span className="stat-value">
                <CountUp value={verifiedDeliveries} />
              </span>
              <span className="stat-sub">of {recentDeliveries.length} recent, on-chain</span>
            </div>
          </>
        )}
      </section>

      <section className="panel-grid">
        <div className="panel panel-wide">
          <h2>District Needs by Urgency</h2>
          <p className="table-hint">
            Worst unmet share across a district's resources (units differ per resource, so
            this compares as a percentage), coloured by its most severe urgency level.
          </p>
          {loading ? (
            <SkeletonChart height={360} />
          ) : zoneUrgency.length === 0 ? (
            <EmptyState />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={Math.max(260, zoneUrgency.length * 26)}>
                <BarChart data={zoneUrgency} layout="vertical" margin={{ left: 24, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" horizontal={false} />
                  <XAxis
                    type="number"
                    domain={[0, 100]}
                    stroke="var(--axis)"
                    fontSize={12}
                    tickFormatter={(v) => `${Math.round(Number(v))}%`}
                  />
                  <YAxis
                    type="category"
                    dataKey="zone_name"
                    stroke="var(--axis)"
                    fontSize={11}
                    width={150}
                  />
                  <Tooltip formatter={(value) => [`${Math.round(Number(value))}%`, "Unmet"]} />
                  <Bar dataKey="unmet_pct" radius={[0, 4, 4, 0]}>
                    {zoneUrgency.map((row) => (
                      <Cell key={row.zone_name} fill={URGENCY_FILL[row.urgency_level]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="legend-row">
                {(["critical", "medium", "low"] as UrgencyLevel[]).map((u) => (
                  <span className="legend-item" key={u}>
                    <span className="legend-swatch" style={{ background: URGENCY_FILL[u] }} />
                    {URGENCY_LABEL[u]}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="panel">
          <h2>Coverage by Resource</h2>
          <p className="table-hint">Share of estimated need met so far, per resource type.</p>
          {loading ? (
            <SkeletonChart height={280} />
          ) : resourceCoverage.length === 0 ? (
            <EmptyState />
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={resourceCoverage}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                <XAxis dataKey="resource_type" stroke="var(--axis)" fontSize={12} />
                <YAxis
                  domain={[0, 100]}
                  stroke="var(--axis)"
                  fontSize={12}
                  tickFormatter={(v) => `${Math.round(Number(v))}%`}
                />
                <Tooltip
                  formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name as string]}
                />
                <Legend wrapperStyle={{ fontSize: "0.8rem" }} />
                <Bar dataKey="fulfilled_pct" name="Met" stackId="c" fill="var(--accent-fulfilled)" />
                <Bar
                  dataKey="unmet_pct"
                  name="Unmet"
                  stackId="c"
                  fill="var(--accent-need)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="panel">
          <h2>Response Trend</h2>
          <p className="table-hint">
            Needs logged vs. deliveries recorded per day (counts — resource quantities
            aren't comparable across units).
          </p>
          {loading ? (
            <SkeletonChart height={260} />
          ) : responseTrend.length === 0 ? (
            <EmptyState />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={responseTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                <XAxis dataKey="day" stroke="var(--axis)" fontSize={11} />
                <YAxis
                  allowDecimals={false}
                  stroke="var(--axis)"
                  fontSize={12}
                  tickFormatter={(v) => number(Number(v))}
                />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: "0.8rem" }} />
                <Line
                  type="monotone"
                  dataKey="requests_count"
                  name="Needs logged"
                  stroke="var(--accent-need)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="deliveries_count"
                  name="Deliveries"
                  stroke="var(--accent-fulfilled)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="panel panel-wide">
          <h2>District Resource Gaps</h2>
          <p className="table-hint">
            Estimated need (Sphere standards) minus recorded deliveries, per district and
            resource — each row in its own unit. Filter by urgency, click a column to sort.
          </p>
          {!loading && zoneGaps.length > 0 && (
            <div className="gap-filters">
              {(["all", "critical", "medium", "low"] as const).map((u) => (
                <button
                  key={u}
                  type="button"
                  className={`gap-filter${gapUrgency === u ? " is-active" : ""}`}
                  onClick={() => setGapUrgency(u)}
                >
                  {u === "all" ? "All" : URGENCY_LABEL[u]} ({urgencyCounts[u]})
                </button>
              ))}
            </div>
          )}
          <div className="table-wrap">
            {loading ? (
              <SkeletonTable rows={8} cols={7} />
            ) : zoneGaps.length === 0 ? (
              <EmptyState />
            ) : (
              <table className="sortable">
                <thead>
                  <tr>
                    <th onClick={() => toggleGapSort("zone_name")}>Zone{sortArrow("zone_name")}</th>
                    <th onClick={() => toggleGapSort("resource_type")}>
                      Resource{sortArrow("resource_type")}
                    </th>
                    <th>Unit</th>
                    <th onClick={() => toggleGapSort("quantity_needed")}>
                      Needed{sortArrow("quantity_needed")}
                    </th>
                    <th onClick={() => toggleGapSort("quantity_fulfilled")}>
                      Fulfilled{sortArrow("quantity_fulfilled")}
                    </th>
                    <th onClick={() => toggleGapSort("unmet_need")}>Unmet{sortArrow("unmet_need")}</th>
                    <th onClick={() => toggleGapSort("urgency_level")}>
                      Urgency{sortArrow("urgency_level")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleGaps.map((g) => (
                    <tr key={`${g.zone_name}-${g.resource_type}`}>
                      <td>{g.zone_name}</td>
                      <td>{g.resource_type}</td>
                      <td className="unit-cell">{g.unit}</td>
                      <td>{number(g.quantity_needed)}</td>
                      <td>{number(g.quantity_fulfilled)}</td>
                      <td className="unmet-cell">{number(g.unmet_need)}</td>
                      <td>
                        <span className={`urgency-badge urgency-${g.urgency_level}`}>
                          {URGENCY_LABEL[g.urgency_level]}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {visibleGaps.length === 0 && (
                    <tr>
                      <td colSpan={7} className="empty-state">
                        No {gapUrgency} gaps.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel panel-wide">
          <h2>AI Situation Briefing</h2>
          <p className="table-hint">
            Gemini reads the current zone gaps and 30-day trend and returns a ranked action
            list — each zone with a reason, a recommended move, and its confidence.
          </p>
          <div className="briefing-actions">
            <button
              className="btn-briefing"
              onClick={generateBriefing}
              disabled={briefingLoading || loading}
            >
              {briefingLoading ? "Generating…" : briefing ? "Regenerate Briefing" : "Generate Briefing"}
            </button>
            <button
              className="btn-briefing btn-secondary"
              onClick={downloadPdf}
              disabled={pdfLoading || loading}
            >
              {pdfLoading ? "Preparing PDF…" : "Download as PDF"}
            </button>
          </div>
          {briefingError && <p className="upload-error">{briefingError}</p>}
          {briefingLoading && !briefing && (
            <div className="briefing-text">
              <SkeletonText lines={5} />
            </div>
          )}
          {briefing && (
            <>
              {briefing.briefing && <div className="briefing-text">{briefing.briefing}</div>}
              {briefing.priorities.length > 0 && (
                <ol className="priority-list">
                  {briefing.priorities.map((p) => (
                    <li key={p.rank} className="priority-card">
                      <div className="priority-head">
                        <span className="priority-rank">{p.rank}</span>
                        <span className="priority-zone">{p.zone}</span>
                        <span className={`urgency-badge urgency-${p.urgency}`}>
                          {URGENCY_LABEL[p.urgency as UrgencyLevel] ?? p.urgency}
                        </span>
                        <span className={`confidence-chip confidence-${p.confidence}`}>
                          {p.confidence} confidence
                        </span>
                      </div>
                      <p className="priority-reason">{p.reason}</p>
                      <p className="priority-action">
                        <strong>Do:</strong> {p.recommended_action}
                      </p>
                      {p.key_resources.length > 0 && (
                        <div className="priority-resources">
                          {p.key_resources.map((r) => (
                            <span key={r} className="resource-chip">
                              {r}
                            </span>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
        </div>

        <div className="panel panel-wide">
          <h2>Ask ReliefTrace</h2>
          <p className="table-hint">
            A question in plain English. Gemini decides which live Snowflake queries to run
            (via function calling), then answers from the results — no made-up numbers.
          </p>
          <form className="ask-form" onSubmit={runAsk}>
            <input
              type="text"
              value={askQuestion}
              onChange={(e) => setAskQuestion(e.target.value)}
              placeholder="e.g. Which zone has the worst medical shortage?"
              maxLength={400}
            />
            <button type="submit" className="btn-briefing" disabled={askLoading || askQuestion.trim().length < 3}>
              {askLoading ? "Thinking…" : "Ask"}
            </button>
          </form>
          <div className="ask-samples">
            {ASK_SAMPLES.map((s) => (
              <button
                key={s}
                type="button"
                className="ask-sample"
                onClick={() => setAskQuestion(s)}
                disabled={askLoading}
              >
                {s}
              </button>
            ))}
          </div>
          {askError && <p className="upload-error">{askError}</p>}
          {askLoading && !askResult && (
            <div className="briefing-text">
              <SkeletonText lines={2} />
            </div>
          )}
          {askResult && (
            <div className="ask-answer">
              <p className="ask-question">“{askResult.question}”</p>
              <div className="briefing-text">{askResult.answer}</div>
              {askResult.tools_used.length > 0 && (
                <div className="ask-trace">
                  <span className="ask-trace-label">Queried:</span>
                  {askResult.tools_used.map((t, i) => (
                    <span key={`${t}-${i}`} className="tool-chip">
                      {t.replace(/^get_/, "").replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="panel panel-wide">
          <h2>Recent Deliveries</h2>
          <p className="table-hint">
            Each delivery is anchored with a Solana devnet memo transaction encoding zone,
            resource, quantity and donor org.
          </p>
          <div className="table-wrap">
            {loading ? (
              <SkeletonTable rows={8} cols={6} />
            ) : recentDeliveries.length === 0 ? (
              <EmptyState />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Zone</th>
                    <th>Donor Org</th>
                    <th>Resource</th>
                    <th>Quantity</th>
                    <th>Date</th>
                    <th>Verify</th>
                  </tr>
                </thead>
                <tbody>
                  {recentDeliveries.map((d) => (
                    <tr key={d.delivery_id}>
                      <td>{d.zone_name}</td>
                      <td>
                        <span className="donor-org">{d.donor_org}</span>
                        {d.donor_email && <span className="donor-email">{d.donor_email}</span>}
                        {d.cause_note && <span className="donor-note">{d.cause_note}</span>}
                      </td>
                      <td>{d.resource_type}</td>
                      <td>{number(d.quantity_sent)}</td>
                      <td>{d.delivery_date}</td>
                      <td>
                        {d.solana_tx_sig ? (
                          <a
                            className="verify-link"
                            href={explorerUrl(d.solana_tx_sig)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Verify on-chain
                          </a>
                        ) : (
                          <span className="tx-chip-empty">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>

      <footer className="methodology-note">
        <strong>Methodology.</strong> The 15 districts are real areas affected by the 2024 Assam
        floods (~400,000 people across 19 districts) and the 2025 Punjab floods (~3.54 million
        across 13+ districts); affected population is split evenly within each state, since public
        per-district figures aren&rsquo;t available. Per-resource need is computed from Sphere
        Handbook (2018) minimum standards — water 15 L/person/day and food ~2.1 kg/person/day over
        a 30-day window, ~1 medical kit per 500 people, ~1 tent per 5, 1 clothing set per person.
        Fulfilled amounts are illustrative of early-response gaps, not sourced. Deliveries and
        their on-chain signatures are real, from live submissions.
      </footer>
    </div>
  );
}
