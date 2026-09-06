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
| `RELIEF_REQUESTS` | district, resource type, quantity needed + **unit**, quantity fulfilled, urgency, date, **affected population** |
| `RELIEF_DELIVERIES` | donor org, cause note, email, zone, resource, quantity, date, **Solana tx signature**, source (`public`) |

**The need side is grounded in real events.** `RELIEF_REQUESTS` is a fixed
dataset of 15 districts hit by the **2024 Assam floods** (~400,000 people across
19 districts) and the **2025 Punjab floods** (~3.54 million across 13+
districts). Affected population is split evenly within each state — public
per-district figures aren't available — and per-resource `QUANTITY_NEEDED` is
computed from **Sphere Handbook (2018) humanitarian minimum standards** (water
15 L/person/day and food ~2.1 kg/person/day over a 30-day window, ~1 medical kit
per 500 people, ~1 tent per 5, 1 clothing set per person). Each row carries its
`UNIT` (litres / kg / kits / tents / sets); `QUANTITY_FULFILLED` starts low to
reflect early-response gaps and `URGENCY_LEVEL` is derived from the resulting
unmet-need %. This is a calculated estimate, not a live operational feed —
granular real-time need data isn't published at this resolution.

The **delivery side is real**: every `RELIEF_DELIVERIES` row comes from a live
dashboard submission, `INSERT`ed with its confirmed on-chain signature. No seed
deliveries.

Every analytics endpoint is a real SQL query against Snowflake — district gap
rollups, per-resource coverage, a daily needs-vs-deliveries trend, and total
people affected. Connection is pooled and results cached (see Redis below).
Because units differ per resource, the dashboard never sums across them — it
compares as a **percentage of need unmet**.

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

### ✨ Google AI (Gemini) — grounded on the live numbers

Three ways, all on `gemini-3.6-flash`, all fed only real Snowflake data and told
never to invent numbers or compare across units:

- **Situation briefing** (`GET /api/insights/ai-briefing`) — Gemini returns
  **structured JSON** (schema-constrained): a narrative plus a ranked list of
  priority districts, each with a reason, a recommended action, key resources
  and a confidence level. Rendered as action cards. Cached 1 h.
- **Ask ReliefTrace** (`POST /api/ask`) — a plain-English question answered with
  **function calling**: Gemini picks from five tools that run the real insight
  queries, we execute them and feed results back, and the reply lists which
  tools it used. Off-topic / unanswerable questions get a fixed fallback line.
- **PDF briefing** (`GET /api/insights/ai-briefing.pdf`) — the briefing plus a
  top-10 gap table rendered to a one-page PDF (reportlab); also attached to the
  donor receipt email.

---

## Architecture

```
React + Vite (single page)
        │  fetch (JSON) + EventSource (live updates)
        ▼
FastAPI  ──────────────► Snowflake      (requests, deliveries, analytics)
   │     ──────────────► Solana devnet  (memo tx per contribution)
   │     ──────────────► Gemini API     (briefing, Q&A via function calling, PDF)
   │     ──────────────► SMTP           (donor receipt email — optional)
   └──── Redis  ─┬─────► insight-query cache (falls back to in-process)
                 └─────► pub/sub backplane for the live SSE feed (multi-replica)
```

The FastAPI app is split into layers: `app/core` (config, logging, cache,
event bus), `app/db` (Snowflake connection pool), `app/services` (queries +
business logic), `app/api/routes` (thin routers).

### Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | — | service info (name, health/docs links) |
| `GET` | `/health` | — | liveness + current SSE client count |
| `GET` | `/api/dashboard` | — | every insight payload + total people affected, one round trip |
| `GET` | `/api/insights/zone-gaps` | — | unmet need per district + resource, with unit + urgency |
| `GET` | `/api/insights/response-trend` | — | needs logged vs. deliveries per day |
| `GET` | `/api/insights/resource-breakdown` | — | needed vs. fulfilled per resource type |
| `GET` | `/api/insights/ai-briefing` | `X-API-Key` | structured Gemini situation briefing (JSON) |
| `GET` | `/api/insights/ai-briefing.pdf` | `X-API-Key` | the briefing + top-10 gap table as a PDF |
| `POST` | `/api/ask` | `X-API-Key` | plain-English question, answered via Gemini function calling |
| `GET` | `/api/deliveries/recent` | — | latest deliveries with verify links |
| `GET` | `/api/zones`, `/api/resource-types` | — | form options |
| `GET` | `/api/stream` | — | Server-Sent Events; one `message` per new contribution |
| `POST` | `/api/contribute` | `X-API-Key` | on-chain memo → store in Snowflake → broadcast → email receipt |

`X-API-Key` is only enforced when the backend has `API_KEY` set; unset = auth
disabled (local dev). Swagger (`/docs`, non-production) shows the padlock and an
**Authorize** button for the protected routes.

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
│   │   ├── services/             insights, contributions, briefing, ask, gemini, pdf, email, solana
│   │   └── api/routes/           health, insights, contribute, briefing, ask, stream
│   ├── scripts/                  run-once utilities (python -m scripts.<name>)
│   │   ├── generate_data.py      real-district need dataset (Sphere standards) → data/relief_requests.csv
│   │   ├── load_to_snowflake.py  PUT + TRUNCATE + COPY INTO (RELIEF_REQUESTS only)
│   │   └── anchor_deliveries.py  batch-anchor rows missing a signature (optional)
│   ├── sql/schema.sql            table definitions (run in Snowsight)
│   ├── sql/migrations/           incremental ALTERs (run in order after schema.sql)
│   ├── data/                     generated CSVs (git-ignored)
│   └── keys/                     Snowflake key + Solana wallet (git-ignored)
└── frontend/
    ├── public/                   favicons + site.webmanifest
    └── src/
        ├── pages/Dashboard.tsx   the UI
        ├── hooks/useDashboard.ts initial load + live (SSE) updates + derived stats
        ├── components/           charts, skeletons, count-up, Combobox (zone field)
        └── lib/
            ├── api.ts            typed fetch client (sends X-API-Key when set)
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

# optional: gate the write / paid endpoints with a shared key
doppler secrets set API_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
doppler secrets set VITE_API_KEY="<same value as API_KEY>"

# optional: email the donor a receipt (any SMTP provider / Gmail App Password)
doppler secrets set SMTP_HOST=smtp.gmail.com SMTP_USER=you@gmail.com \
                    SMTP_PASSWORD=<app-password> SMTP_FROM='ReliefTrace <you@gmail.com>'
```

#### Full variable reference

**Backend** (`backend/.env.example` is the canonical checklist):

| Var | Required? | Notes |
| --- | --- | --- |
| `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER` | **yes** | account identifier + login name |
| `SNOWFLAKE_PRIVATE_KEY_PATH` **or** `SNOWFLAKE_PRIVATE_KEY` | **yes** | key-pair auth; `_PATH` locally, paste the PEM in `_KEY` on a host where `keys/` isn't uploaded. `SNOWFLAKE_PASSWORD` is a fallback but fails for MFA users |
| `SNOWFLAKE_DATABASE` / `SNOWFLAKE_SCHEMA` / `SNOWFLAKE_WAREHOUSE` / `SNOWFLAKE_ROLE` | no | default to `RELIEFTRACE_DB` / `PUBLIC` / `GENEROSITY_WH` / none |
| `SNOWFLAKE_POOL_SIZE` | no | connection pool size, default `3` (keep < 5) |
| `GEMINI_API_KEY` | for AI | without it, `/api/insights/ai-briefing`, `.pdf` and `/api/ask` return 503; everything else works |
| `GEMINI_MODEL` | no | default `gemini-3.6-flash` |
| `API_KEY` | no | when set, `X-API-Key` is required on `/api/contribute`, `/api/ask`, `/api/insights/ai-briefing[.pdf]`. Unset = auth off |
| `REDIS_URL` | no | insight cache + SSE pub/sub backplane; falls back to in-process |
| `EVENTS_CHANNEL` | no | Redis pub/sub channel, default `relieftrace:events` |
| `SMTP_HOST` | no | set to enable donor receipt emails |
| `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_STARTTLS` / `SMTP_FROM` | no | defaults: `587` / — / — / `true` / `ReliefTrace <noreply@relieftrace.local>`. Port `465` uses implicit TLS |
| `FRONTEND_ORIGIN` | prod | comma-separated CORS allowlist, default localhost:5173/5174 |
| `ENVIRONMENT` | no | `production` disables `/docs`, `/redoc`, `/openapi.json` |
| `LOG_LEVEL` | no | `INFO` default |
| `LOGFIRE_TOKEN` | no | enables Pydantic Logfire tracing; no-op without it |
| `SOLANA_CLUSTER` / `SOLANA_RPC_URL` | no | default `devnet` / public devnet RPC |
| `SOLANA_WALLET_SECRET` | on a host | the 64-int `keys/wallet.json` array, for hosts where `keys/` isn't uploaded |

**Frontend** (`frontend/.env.example`), all build-time (`VITE_*` is inlined — rebuild to change):

| Var | Notes |
| --- | --- |
| `VITE_API_BASE_URL` | backend URL, default `http://localhost:8000` |
| `VITE_SOLANA_CLUSTER` | for the "Verify on-chain" explorer links, default `devnet` |
| `VITE_API_KEY` | only if the backend has `API_KEY` set; sent as `X-API-Key`. Note: readable in the shipped bundle — it deters casual abuse, not a determined attacker |

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

### 3. Snowflake schema + need data

Run **`backend/sql/schema.sql`** in a Snowsight worksheet (creates the database
and both tables), then apply the migrations in **`backend/sql/migrations/`** in
order (they add `CAUSE_NOTE` to deliveries and `UNIT` / `AFFECTED_POPULATION` to
requests).

Load the real-district need dataset (from `backend/`):

```bash
python -m scripts.generate_data              # 75 request rows (15 districts x 5 resources) → data/
doppler run -- python -m scripts.load_to_snowflake   # TRUNCATE + reload RELIEF_REQUESTS only
```

`load_to_snowflake` never touches `RELIEF_DELIVERIES` — those rows are live
submissions. The dataset is fixed and deterministic, so re-running is safe.

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
real payments, admin panels, multi-page routing, database replication/sharding,
Docker, or any infrastructure beyond FastAPI, React, Snowflake, Solana devnet,
Gemini, Redis, and an optional SMTP server. Auth is limited to one optional
shared API key on the write / paid endpoints — there is no login or per-user
identity. Outbound email is a single fire-and-forget donor receipt, nothing
more.

## Known limitations

- **Devnet faucet limits.** The Solana faucet rate-limits by IP and address;
  first-time funding sometimes needs the web faucet with a GitHub sign-in.
- **Gemini key required for the AI features.** Without `GEMINI_API_KEY` the
  briefing, its PDF, and Ask ReliefTrace return 503; everything else works. The
  PDF is also skipped from the receipt email in that case.
- **Rate-limit state is per-process.** The Snowflake pool and the cache both
  scale out (the cache and the SSE fan-out share Redis), but slowapi's
  rate-limit counters live in process memory — behind multiple replicas each
  gets its own allowance. Point slowapi at Redis to fix.
- **Need data is a calculated estimate.** The district need figures come from
  Sphere-standard math on reported affected-population totals, not a live
  operational feed — that granularity of real-time need data isn't public. The
  `QUANTITY_FULFILLED` values on `RELIEF_REQUESTS` are illustrative of
  early-response gaps, not sourced; only the deliveries (and their on-chain
  signatures) are real.
- **Mixed units.** Resources are measured in different units (litres, kg, kits,
  tents, sets), so the dashboard compares by *percentage of need unmet* and
  never sums raw quantities across resources.
