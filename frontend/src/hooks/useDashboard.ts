// Owns all dashboard read-state: the initial combined load, live updates over
// SSE, a manual reload, and the derived stat-card numbers.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  type DashboardSnapshot,
  type RecentDelivery,
  type ResourceBreakdown,
  type ResponseTrendPoint,
  type ZoneGap,
} from "../lib/api";
import { subscribeToLiveEvents, type LiveStatus } from "../lib/liveEvents";

const DELIVERIES_LIMIT = 25;
// After a live contribution we refetch the rollups (gaps/trend/breakdown), but
// debounced so a burst of submissions triggers one refetch, not many.
const ROLLUP_REFRESH_DEBOUNCE_MS = 4000;

export interface DashboardState {
  zoneGaps: ZoneGap[];
  resourceBreakdown: ResourceBreakdown[];
  responseTrend: ResponseTrendPoint[];
  recentDeliveries: RecentDelivery[];
  loading: boolean;
  error: string | null;
  live: LiveStatus;
  stats: {
    peopleAffected: number;
    criticalZones: number;
    verifiedDeliveries: number;
  };
  reload: () => void;
}

export function useDashboard(): DashboardState {
  const [zoneGaps, setZoneGaps] = useState<ZoneGap[]>([]);
  const [resourceBreakdown, setResourceBreakdown] = useState<ResourceBreakdown[]>([]);
  const [responseTrend, setResponseTrend] = useState<ResponseTrendPoint[]>([]);
  const [recentDeliveries, setRecentDeliveries] = useState<RecentDelivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<LiveStatus>("connecting");
  const [peopleAffected, setPeopleAffected] = useState(0);

  const applySnapshot = useCallback((snap: DashboardSnapshot) => {
    setZoneGaps(snap.zone_gaps);
    setResourceBreakdown(snap.resource_breakdown);
    setResponseTrend(snap.response_trend);
    setRecentDeliveries(snap.recent_deliveries);
    setPeopleAffected(snap.affected_population);
  }, []);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .dashboard(DELIVERIES_LIMIT)
      .then(applySnapshot)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [applySnapshot]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Live updates: show new deliveries instantly, refresh rollups debounced.
  const rollupTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const scheduleRollupRefresh = () => {
      if (rollupTimer.current) clearTimeout(rollupTimer.current);
      rollupTimer.current = setTimeout(() => {
        api
          .dashboard(DELIVERIES_LIMIT)
          .then(applySnapshot)
          .catch(() => {
            /* keep the optimistic row; next manual reload will reconcile */
          });
      }, ROLLUP_REFRESH_DEBOUNCE_MS);
    };

    const unsubscribe = subscribeToLiveEvents({
      onStatus: setLive,
      onContribution: (delivery) => {
        setRecentDeliveries((prev) =>
          prev.some((d) => d.delivery_id === delivery.delivery_id)
            ? prev
            : [delivery, ...prev].slice(0, DELIVERIES_LIMIT),
        );
        scheduleRollupRefresh();
      },
    });

    return () => {
      unsubscribe();
      if (rollupTimer.current) clearTimeout(rollupTimer.current);
    };
  }, [applySnapshot]);

  const stats = useMemo(
    () => ({
      peopleAffected,
      criticalZones: new Set(
        zoneGaps.filter((g) => g.urgency_level === "critical").map((g) => g.zone_name),
      ).size,
      verifiedDeliveries: recentDeliveries.filter((d) => d.solana_tx_sig).length,
    }),
    [peopleAffected, zoneGaps, recentDeliveries],
  );

  return {
    zoneGaps,
    resourceBreakdown,
    responseTrend,
    recentDeliveries,
    loading,
    error,
    live,
    stats,
    reload,
  };
}
