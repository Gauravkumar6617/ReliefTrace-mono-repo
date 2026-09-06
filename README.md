# ReliefTrace

**Aid you can actually verify.**

A public disaster-relief coordination dashboard. Anyone can log a relief
contribution (a resource, a quantity, a zone), watch it get written to a data
warehouse **and** anchored on a public blockchain in the same request, and then
read a live picture of where the unmet need actually is — including a plain-language
situation briefing written by an AI from the current numbers.

No login. No accounts. No real money. It tracks *physical* aid — food, water,
shelter, medical supplies, clothing — moving between zones and the people and
orgs sending it.

Built for the **DEV Community Weekend Challenge — Generosity Edition**, aiming at
*Best use of Snowflake*, *Best use of Solana*, and *Best use of Google AI*.

---

## Why it exists

When a disaster response is underway, two questions are surprisingly hard to
answer honestly:

1. **Where is the need going unmet right now?** Not "how much was pledged" —
   how much was *requested* minus how much actually *arrived*, per zone, per
   resource.
2. **Did that donation actually happen?** A dashboard number is easy to fudge.
   A confirmed transaction on a public ledger is not.

ReliefTrace answers both on one screen: the gap analytics come from Snowflake,
and every contribution carries a Solana transaction signature you can click
through to a block explorer and verify yourself.

---

## How each technology is used

### ❄️ Snowflake — the source of truth for need vs. delivery

Two tables in `RELIEFTRACE_DB.PUBLIC`:

| Table | What it holds |
| --- | --- |
| `RELIEF_REQUESTS` | zone, resource type, quantity needed, quantity fulfilled, urgency, date |
| `RELIEF_DELIVERIES` | donor, email, zone, resource, quantity, date, **Solana tx signature**, source (`seed` / `public`) |

Every analytics endpoint is a real SQL query against Snowflake — zone-level gap
rollups, a 30-day requested-vs-delivered trend, and a per-resource
supply-vs-demand breakdown. Contributions submitted through the site are
`INSERT`ed straight into `RELIEF_DELIVERIES` with their confirmed on-chain
signature. Connection is pooled and query results are cached (see Redis below)
so the dashboard stays fast without hammering the warehouse.

### ◎ Solana — the verification layer

When you submit a contribution, the API:

1. loads a local **devnet** keypair (generated on first run, funded from the
   public faucet — never real funds),
2. sends a single **Memo-program transaction** encoding
   `ReliefTrace|zone=…|resource=…|qty=…|donor=…`,
3. waits for confirmation, then stores the returned signature in Snowflake.

The dashboard's "Verify on-chain" links go straight to Solana Explorer on
devnet. The donor's **email is deliberately never written on-chain** — only the
name, resource, quantity and zone.

### ✨ Google AI (Gemini) — the situation briefing

The `ai-briefing` endpoint takes the *current* zone-gap data and 30-day trend
straight out of Snowflake, hands it to **Gemini** (`gemini-3.6-flash`), and asks
it to name the zones that need intervention first and explain the reasoning in
plain language — a short paragraph plus a prioritized shortlist. It's grounded
on the live numbers and told not to invent data.

---

## Architecture

```
React + Vite (single page)
        │  fetch (JSON) + EventSource (live updates)
        ▼
FastAPI  ──────────────► Snowflake      (requests, deliveries, analytics)
   │     ──────────────► Solana devnet  (memo tx per contribution)
   │     ──────────────► Gemini API     (situation briefing)
   └──── Redis  ─┬─────► insight-query cache (falls back to in-process)
                 └─────► pub/sub backplane for the live SSE feed (multi-replica)
```

The FastAPI app is split into layers: `app/core` (config, logging, cache,
event bus), `app/db` (Snowflake connection pool), `app/services` (queries +
business logic), `app/api/routes` (thin routers).

### Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/dashboard` | — | all four insight payloads in one round trip (queries run concurrently) |
| `GET` | `/api/insights/zone-gaps` | — | unmet need per zone + resource, with urgency |
| `GET` | `/api/insights/response-trend` | — | requested vs. delivered per day |
| `GET` | `/api/insights/resource-breakdown` | — | supply vs. demand per resource type |
| `GET` | `/api/insights/ai-briefing` | `X-API-Key` | Gemini-written situation briefing |
| `GET` | `/api/deliveries/recent` | — | latest deliveries with verify links |
| `GET` | `/api/zones`, `/api/resource-types` | — | form options |
| `GET` | `/api/stream` | — | Server-Sent Events; one `message` per new contribution |
| `GET` | `/health` | — | liveness + current SSE client count |
| `POST` | `/api/contribute` | `X-API-Key` | write delivery → Solana memo → store signature → broadcast |

`X-API-Key` is only enforced when the backend has `API_KEY` set; unset =
auth disabled. Swagger (`/docs`, when the backend is running) shows the
padlock and an **Authorize** button for the two protected routes.

The contribution form also carries a **honeypot** field (`website`): hidden
from real users, rejected server-side with `400` if a bot fills it.

---

## Project layout

```
snow-donation/
├── README.md
├── doppler.yaml                  Doppler project/config binding
├── backend/
│   ├── app/                      the FastAPI application (importable package)
│   │   ├── main.py               app factory, middleware, lifespan (prewarm + event relay)
│   │   ├── schemas.py            request/response models + validation
│   │   ├── core/
│   │   │   ├── config.py         one Settings object; loads .env once
│   │   │   ├── logging.py        stdout + optional Logfire tracing
│   │   │   ├── cache.py          Redis-backed cache (falls back to in-process)
│   │   │   ├── events.py         SSE broadcaster + Redis pub/sub fan-out
│   │   │   └── security.py       X-API-Key dependency (Swagger padlock)
│   │   ├── db/pool.py            Snowflake connection pool
│   │   ├── services/             insights, contributions, briefing, solana
│   │   └── api/routes/           health, insights, contribute, briefing, stream
│   ├── scripts/                  run-once utilities (python -m scripts.<name>)
│   │   ├── generate_data.py      synthetic requests/deliveries → data/*.csv
│   │   ├── load_to_snowflake.py  PUT + COPY INTO
│   │   └── anchor_deliveries.py  batch-anchor seed rows on Solana (optional)
│   ├── sql/schema.sql            table definitions (run in Snowsight)
│   ├── data/                     generated CSVs (git-ignored)
│   └── keys/                     Snowflake key + Solana wallet (git-ignored)
└── frontend/
    └── src/
        ├── pages/Dashboard.tsx   the UI
        ├── hooks/useDashboard.ts initial load + live (SSE) updates + derived stats
        ├── components/           charts, skeleton loaders, count-up
        └── lib/
            ├── api.ts            typed fetch client
            └── liveEvents.ts     EventSource wrapper for /api/stream
```

---

## Running it locally

You need: a Snowflake account, a Gemini API key, and Python 3.12 + Node.

### 1. Secrets — Doppler

Configuration is read from environment variables, and locally those come from
[**Doppler**](https://doppler.com) — there is **no `.env` file to create**.
`backend/.env.example` is just the checklist of which variables exist.

```bash
# one-time: install the CLI  (see docs.doppler.com/docs/install-cli)
brew install dopplerhq/cli/doppler

cd backend
doppler login
doppler setup                 # links this dir to the project/config in doppler.yaml

# add your secrets to that config
doppler secrets set SNOWFLAKE_ACCOUNT=xxxxx-xxxxx
doppler secrets set SNOWFLAKE_USER=you
doppler secrets set SNOWFLAKE_PRIVATE_KEY_PATH=keys/snowflake_rsa_key.p8
doppler secrets set GEMINI_API_KEY=AIza...
doppler secrets set REDIS_URL='rediss://default:...@...upstash.io:6379'

# optional: require an API key on POST /api/contribute and the AI briefing
doppler secrets set API_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
doppler secrets set VITE_API_KEY="<same value as API_KEY>"
```

Other optional knobs (see `backend/.env.example` for the full list):
`SNOWFLAKE_POOL_SIZE` (default `3`), `EVENTS_CHANNEL` (default
`relieftrace:events`).

Everything then runs through `doppler run --`, which injects the variables for
that one command:

```bash
doppler run -- python -m app.main
```

The repo-root `doppler.yaml` applies to `frontend/` too, so `doppler run -- pnpm
dev` there picks up the same config (add the `VITE_*` variables to it as well).

### 2. Redis — Upstash (recommended) or local

Insight-query results are cached so the dashboard doesn't re-run the same
Snowflake queries on every load, and the cache survives backend restarts.
Redis also carries the pub/sub messages behind the live `/api/stream` feed —
needed only if you run more than one backend replica; a single process
broadcasts in-memory without it.

- **Upstash:** create a free Redis database at
  [upstash.com](https://upstash.com), then
  `doppler secrets set REDIS_URL='rediss://default:...@...upstash.io:6379'`.
  TLS is handled automatically.
- **Local:** `docker run -d -p 6379:6379 redis:7-alpine`, then
  `doppler secrets set REDIS_URL=redis://localhost:6379/0`.
- **Neither:** leave `REDIS_URL` unset — it falls back to an in-process cache
  (works fine, just doesn't survive a restart).

### 3. Snowflake schema + data

Run **`backend/sql/schema.sql`** in a Snowsight worksheet (creates the
warehouse, database, and both tables).

Optionally seed the need-side analytics with synthetic data (from `backend/`):

```bash
python -m scripts.generate_data              # ~200 requests, ~150 deliveries → data/
doppler run -- python -m scripts.load_to_snowflake
```

### 4. Fund the Solana devnet wallet

```bash
cd backend
doppler run -- python -m app.services.solana   # prints the wallet address + tries an airdrop
```

The public RPC faucet is aggressively rate-limited. If the airdrop fails, fund
the printed address manually:

```bash
solana airdrop 2 <WALLET_ADDRESS> --url devnet
# or paste it at https://faucet.solana.com (select devnet)
```

You only do this once — the balance persists, and each memo transaction costs
~0.000005 devnet SOL.

### 5. Start

```bash
# terminal 1
cd backend  && doppler run -- python -m app.main         # http://localhost:8000

# terminal 2
cd frontend && pnpm install && doppler run -- pnpm dev   # http://localhost:5173
```

Open **http://localhost:5173**, fill in the form, hit **Submit contribution**,
and watch it get recorded and verified.

---

## Non-goals

Deliberately not built, to keep the surface honest and small: user accounts,
real payments, email sending, admin panels, multi-page routing, database
replication/sharding, Docker, or any infrastructure beyond FastAPI, React,
Snowflake, Solana devnet, Gemini, and Redis. Auth is limited to one optional
shared API key on the two write/paid endpoints — there is no login or per-user
identity.

## Known limitations

- **Devnet faucet limits.** The Solana faucet rate-limits by IP and address;
  first-time funding sometimes needs the web faucet with a GitHub sign-in.
- **Gemini key required for the briefing.** Without `GEMINI_API_KEY` that one
  endpoint returns 503; everything else works.
- **Rate-limit state is per-process.** The Snowflake pool and the cache both
  scale out (the cache and the SSE fan-out share Redis), but slowapi's
  rate-limit counters live in process memory — behind multiple replicas each
  gets its own allowance. Point slowapi at Redis to fix.
- **Seed data is optional.** If you skip the Snowflake seed load, the need-side
  panels stay empty until requests exist — the delivery side is fully driven by
  the live form.
