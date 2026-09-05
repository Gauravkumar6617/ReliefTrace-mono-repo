// Content-shaped placeholders shown while the dashboard data loads, so the
// layout doesn't jump and the wait reads as "loading" rather than "broken".

import type { CSSProperties } from "react";

export function Skeleton({
  width = "100%",
  height = 16,
  radius = 6,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  style?: CSSProperties;
}) {
  return (
    <span
      className="skeleton"
      style={{ width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  );
}

export function SkeletonText({ lines = 3, lastWidth = "60%" }: { lines?: number; lastWidth?: string }) {
  return (
    <span className="skeleton-text">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} height={12} width={i === lines - 1 ? lastWidth : "100%"} />
      ))}
    </span>
  );
}

export function SkeletonStatCard() {
  return (
    <div className="stat-card">
      <Skeleton width={110} height={11} />
      <Skeleton width={80} height={30} style={{ marginTop: 6 }} />
      <Skeleton width={140} height={10} style={{ marginTop: 6 }} />
    </div>
  );
}

export function SkeletonChart({ height = 260 }: { height?: number }) {
  return <Skeleton height={height} radius={8} />;
}

export function SkeletonTable({ rows = 6, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="skeleton-table">
      {Array.from({ length: rows }).map((_, r) => (
        <div className="skeleton-table-row" key={r}>
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} height={12} width={c === 0 ? "22%" : `${Math.round(60 / (cols - 1))}%`} />
          ))}
        </div>
      ))}
    </div>
  );
}
