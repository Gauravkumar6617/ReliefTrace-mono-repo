// Subscribes to the backend's Server-Sent Events stream (GET /api/stream) and
// calls back on every contribution event. EventSource reconnects on its own;
// we surface the connection state so the UI can show a "Live" indicator.

import { BASE_URL, type RecentDelivery } from "./api";

export type LiveStatus = "connecting" | "open" | "closed";

export interface ContributionEvent {
  type: "contribution";
  delivery: RecentDelivery;
}

interface Handlers {
  onContribution: (delivery: RecentDelivery) => void;
  onStatus?: (status: LiveStatus) => void;
}

export function subscribeToLiveEvents({ onContribution, onStatus }: Handlers): () => void {
  if (typeof EventSource === "undefined") {
    onStatus?.("closed");
    return () => {};
  }

  const source = new EventSource(`${BASE_URL}/api/stream`);
  onStatus?.("connecting");

  source.addEventListener("ready", () => onStatus?.("open"));
  source.onopen = () => onStatus?.("open");
  source.onerror = () => onStatus?.(source.readyState === EventSource.CLOSED ? "closed" : "connecting");

  source.addEventListener("message", (e) => {
    try {
      const parsed = JSON.parse((e as MessageEvent).data) as ContributionEvent;
      if (parsed.type === "contribution" && parsed.delivery) {
        onContribution(parsed.delivery);
      }
    } catch {
      /* ignore malformed frames */
    }
  });

  return () => source.close();
}
