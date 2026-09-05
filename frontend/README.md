# ReliefTrace — frontend

React + Vite single-page dashboard. See the [root README](../README.md) for the
full project.

```bash
pnpm install
pnpm dev        # http://localhost:5173  (expects the API on :8000)
pnpm build      # type-check + production build → dist/
```

## Environment

Copy `.env.example` to `.env` (or inject via `doppler run -- pnpm dev`):

| Var | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | FastAPI base URL (default `http://localhost:8000`) |
| `VITE_SOLANA_CLUSTER` | cluster for "Verify on-chain" explorer links (default `devnet`) |

## Where things live

- `src/pages/Dashboard.tsx` — the entire UI: contribution form, stat row,
  urgency-coded zone chart, supply-vs-demand and trend charts, AI briefing
  card, recent-deliveries table.
- `src/components/` — `Skeleton` loaders, `CountUp` animated stat.
- `src/api.ts` — typed fetch client for every endpoint.
