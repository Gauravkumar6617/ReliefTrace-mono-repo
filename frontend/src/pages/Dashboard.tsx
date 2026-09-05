import { useCallback, useEffect, useState, type FormEvent } from "react";
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
  type ContributionResult,
  type RecentDelivery,
  type ResourceBreakdown,
  type ResponseTrendPoint,
  type UrgencyLevel,
  type ZoneGap,
} from "../api";
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
  unmet_need: number;
  urgency_level: UrgencyLevel;
}

// Collapse the per-(zone, resource) gap rows into one bar per zone: total
// unmet need, coloured by that zone's worst urgency.
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
      unmet_need: (prev?.unmet_need ?? 0) + Math.max(0, g.unmet_need),
      urgency_level: worst,
    });
  }
  return [...byZone.values()].sort((a, b) => b.unmet_need - a.unmet_need);
}

export function Dashboard() {
  const [zoneGaps, setZoneGaps] = useState<ZoneGap[]>([]);
  const [resourceBreakdown, setResourceBreakdown] = useState<ResourceBreakdown[]>([]);
  const [responseTrend, setResponseTrend] = useState<ResponseTrendPoint[]>([]);
  const [recentDeliveries, setRecentDeliveries] = useState<RecentDelivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [briefing, setBriefing] = useState<string | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingError, setBriefingError] = useState<string | null>(null);

  const [zones, setZones] = useState<string[]>([]);
  const [resourceOptions, setResourceOptions] = useState<string[]>([]);
  const [form, setForm] = useState({
    donor_name: "",
    donor_email: "",
    resource_type: "",
    quantity: "",
    zone_name: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<ContributionResult | null>(null);

  const loadDashboard = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.zoneGaps(),
      api.resourceBreakdown(),
      api.responseTrend(),
      api.recentDeliveries(25),
    ])
      .then(([gaps, breakdown, trend, deliveries]) => {
        setZoneGaps(gaps);
        setResourceBreakdown(breakdown);
        setResponseTrend(trend);
        setRecentDeliveries(deliveries);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

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
    form.donor_name.trim() !== "" &&
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
        donor_name: form.donor_name.trim(),
        donor_email: form.donor_email.trim(),
        resource_type: form.resource_type,
        quantity: Number(form.quantity),
        zone_name: form.zone_name.trim(),
      });
      setConfirmation(result);
      setForm((f) => ({ ...f, donor_name: "", donor_email: "", quantity: "" }));
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
      const result = await api.aiBriefing();
      setBriefing(result.briefing);
    } catch (err) {
      setBriefingError(err instanceof ApiError ? err.message : "Could not generate briefing.");
    } finally {
      setBriefingLoading(false);
    }
  };

  const totalUnmet = zoneGaps.reduce((sum, g) => sum + Math.max(0, g.unmet_need), 0);
  const criticalZones = new Set(
    zoneGaps.filter((g) => g.urgency_level === "critical").map((g) => g.zone_name),
  ).size;
  const verifiedDeliveries = recentDeliveries.filter((d) => d.solana_tx_sig).length;
  const zoneUrgency = toZoneUrgency(zoneGaps);

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div>
          <span className="brand-eyebrow">ReliefTrace</span>
          <h1>Aid you can actually verify.</h1>
          <p>
            Log a relief contribution and watch it get recorded on a public blockchain, then see
            live zone needs and an AI situation briefing.
          </p>
        </div>
        <div className="header-actions">
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
          <label>
            <span>Your name or organization</span>
            <input
              type="text"
              value={form.donor_name}
              onChange={(e) => setForm({ ...form, donor_name: e.target.value })}
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
            <input
              type="text"
              list="zone-options"
              value={form.zone_name}
              onChange={(e) => setForm({ ...form, zone_name: e.target.value })}
              placeholder="e.g. Riverside District"
              maxLength={80}
              required
            />
            <datalist id="zone-options">
              {zones.map((z) => (
                <option key={z} value={z} />
              ))}
            </datalist>
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
              {confirmation.zone_name}, from {confirmation.donor_name} ({confirmation.donor_email}).
            </p>
            <a
              className="verify-link"
              href={confirmation.explorer_url}
              target="_blank"
              rel="noreferrer"
            >
              View on-chain ↗
            </a>
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
              <span className="stat-label">Total Unmet Need</span>
              <span className="stat-value">
                <CountUp value={Math.round(totalUnmet)} />
              </span>
              <span className="stat-sub">units still owed across all zones</span>
            </div>
            <div className="stat-card stat-card-critical">
              <span className="stat-label">Zones with Critical Gaps</span>
              <span className="stat-value">
                <CountUp value={criticalZones} />
              </span>
              <span className="stat-sub">need urgent intervention</span>
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
          <h2>Zone Needs by Urgency</h2>
          <p className="table-hint">
            Total unmet need per zone, coloured by the zone's most severe urgency level.
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
                  <XAxis type="number" stroke="var(--axis)" fontSize={12} tickFormatter={(v) => number(Number(v))} />
                  <YAxis
                    type="category"
                    dataKey="zone_name"
                    stroke="var(--axis)"
                    fontSize={11}
                    width={140}
                  />
                  <Tooltip formatter={(value) => [number(Number(value)), "Unmet need"]} />
                  <Bar dataKey="unmet_need" radius={[0, 4, 4, 0]}>
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
          <h2>Supply vs. Demand by Resource</h2>
          {loading ? (
            <SkeletonChart height={280} />
          ) : resourceBreakdown.length === 0 ? (
            <EmptyState />
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={resourceBreakdown}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                <XAxis dataKey="resource_type" stroke="var(--axis)" fontSize={12} />
                <YAxis stroke="var(--axis)" fontSize={12} tickFormatter={(v) => number(Number(v))} />
                <Tooltip formatter={(value) => number(Number(value))} />
                <Legend wrapperStyle={{ fontSize: "0.8rem" }} />
                <Bar dataKey="total_needed" name="Needed" fill="var(--accent-need)" radius={[4, 4, 0, 0]} />
                <Bar
                  dataKey="total_fulfilled"
                  name="Fulfilled"
                  fill="var(--accent-fulfilled)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="panel">
          <h2>Response Trend</h2>
          <p className="table-hint">Requests raised vs. resource units delivered, over the 30-day window.</p>
          {loading ? (
            <SkeletonChart height={260} />
          ) : responseTrend.length === 0 ? (
            <EmptyState />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={responseTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                <XAxis dataKey="day" stroke="var(--axis)" fontSize={11} />
                <YAxis stroke="var(--axis)" fontSize={12} tickFormatter={(v) => number(Number(v))} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: "0.8rem" }} />
                <Line
                  type="monotone"
                  dataKey="quantity_requested"
                  name="Requested"
                  stroke="var(--accent-need)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="quantity_delivered"
                  name="Delivered"
                  stroke="var(--accent-fulfilled)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="panel panel-wide">
          <h2>Zone Resource Gaps</h2>
          <p className="table-hint">
            Unmet need = requested minus fulfilled, per zone and resource. Sorted worst-first.
          </p>
          <div className="table-wrap">
            {loading ? (
              <SkeletonTable rows={8} cols={6} />
            ) : zoneGaps.length === 0 ? (
              <EmptyState />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Zone</th>
                    <th>Resource</th>
                    <th>Needed</th>
                    <th>Fulfilled</th>
                    <th>Unmet</th>
                    <th>Urgency</th>
                  </tr>
                </thead>
                <tbody>
                  {zoneGaps.map((g) => (
                    <tr key={`${g.zone_name}-${g.resource_type}`}>
                      <td>{g.zone_name}</td>
                      <td>{g.resource_type}</td>
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
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel panel-wide">
          <h2>AI Situation Briefing</h2>
          <p className="table-hint">
            Sends the current zone gaps and response trend to Gemini and asks it to prioritize
            which zones need urgent intervention first.
          </p>
          <button className="btn-briefing" onClick={generateBriefing} disabled={briefingLoading || loading}>
            {briefingLoading ? "Generating…" : briefing ? "Regenerate Briefing" : "Generate Briefing"}
          </button>
          {briefingError && <p className="upload-error">{briefingError}</p>}
          {briefingLoading && !briefing && (
            <div className="briefing-text">
              <SkeletonText lines={5} />
            </div>
          )}
          {briefing && <div className="briefing-text">{briefing}</div>}
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
                        {d.donor_org}
                        {d.donor_email && <span className="donor-email">{d.donor_email}</span>}
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
    </div>
  );
}
