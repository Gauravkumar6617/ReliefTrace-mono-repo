// Fetch wrapper for ReliefTrace's read-only insights API. No auth, no
// cookies - every route here is a public GET.

export const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function parseError(res: Response): Promise<never> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
  } catch {
    // no JSON body - fall back to status text
  }
  throw new ApiError(detail, res.status);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) await parseError(res);
  return res.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export type UrgencyLevel = "low" | "medium" | "critical";

export interface ZoneGap {
  zone_name: string;
  resource_type: string;
  quantity_needed: number;
  quantity_fulfilled: number;
  unmet_need: number;
  urgency_level: UrgencyLevel;
}

export interface ResponseTrendPoint {
  day: string;
  requests_count: number;
  quantity_requested: number;
  deliveries_count: number;
  quantity_delivered: number;
}

export interface ResourceBreakdown {
  resource_type: string;
  total_needed: number;
  total_fulfilled: number;
  unmet_need: number;
}

export interface RecentDelivery {
  delivery_id: string;
  zone_name: string;
  donor_org: string;
  donor_email: string | null;
  resource_type: string;
  quantity_sent: number;
  delivery_date: string;
  solana_tx_sig: string | null;
}

export interface AiBriefing {
  briefing: string;
  generated_at: string;
}

export interface DashboardSnapshot {
  zone_gaps: ZoneGap[];
  resource_breakdown: ResourceBreakdown[];
  response_trend: ResponseTrendPoint[];
  recent_deliveries: RecentDelivery[];
}

export interface ContributionInput {
  donor_name: string;
  donor_email: string;
  resource_type: string;
  quantity: number;
  zone_name: string;
}

export interface ContributionResult {
  delivery_id: string;
  donor_name: string;
  donor_email: string;
  resource_type: string;
  quantity: number;
  zone_name: string;
  delivery_date: string;
  solana_tx_sig: string;
  explorer_url: string;
  verified: boolean;
}

export { ApiError };

export const api = {
  dashboard: (deliveriesLimit = 25) =>
    getJson<DashboardSnapshot>(`/api/dashboard?deliveries_limit=${deliveriesLimit}`),
  zoneGaps: () => getJson<ZoneGap[]>("/api/insights/zone-gaps"),
  responseTrend: () => getJson<ResponseTrendPoint[]>("/api/insights/response-trend"),
  resourceBreakdown: () => getJson<ResourceBreakdown[]>("/api/insights/resource-breakdown"),
  recentDeliveries: (limit = 20) =>
    getJson<RecentDelivery[]>(`/api/deliveries/recent?limit=${limit}`),
  aiBriefing: () => getJson<AiBriefing>("/api/insights/ai-briefing"),
  zones: () => getJson<string[]>("/api/zones"),
  resourceTypes: () => getJson<string[]>("/api/resource-types"),
  contribute: (input: ContributionInput) =>
    postJson<ContributionResult>("/api/contribute", input),
};
