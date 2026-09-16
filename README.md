# AI Voice Receptionist for Diagnostic Labs

A voice AI receptionist for a diagnostics lab: callers can check report status, ask about
test/package pricing and offers, register as a new patient, and book/reschedule/cancel
appointments — all handled end-to-end by the agent over a real-time voice call.

The agent's persona name and the lab's branding are **not hardcoded** — they're read from
config (`AGENT_NAME`) and the `lab_info` database row, so renaming or re-skinning for a
different lab is a config/data change, not a code change. This build ships seeded with real
data from `data.json` (Dr Lal PathLabs, Baner/Pune), but that's just sample data.

The one hard product requirement this is built around: **the agent must never state a price,
report status, or appointment detail it hasn't actually looked up, and must never finalize a
booking, reschedule, cancellation, or registration without the caller's explicit confirmation.**
That's enforced structurally (propose → confirm graphs backed by Postgres), not just by prompting.

## Architecture

```
Browser (LiveKit web client) ──► LiveKit Room ──► LiveKit Agent worker (Python)
                                                        │
                                                        ├─ AgentSession(llm=GPTLiveModel(...))
                                                        │     "responses" delegation: GPT-Live's
                                                        │     backend reasoning model picks tools
                                                        │
                                                        └─ @function_tool functions
                                                              │
                                                              ├─ read-only → db/repositories (SQLAlchemy)
                                                              │
                                                              └─ propose_*/confirm_* → LangGraph graphs
                                                                    propose → stage in pending_actions
                                                                    + interrupt() → confirm/discard →
                                                                    commit write or abort, no write
                                                                            │
                                                                            ▼
                                                                     Postgres (Docker)
```

- **Voice layer** (`Agent.instructions`, see `instructions.py`): governs delivery only — tone,
  pacing, when to speak. Never sees the tools.
- **Reasoning layer** (`responses_options["instructions"]`): OpenAI's GPT-Live backend model
  that actually decides which tool to call. This is where the trustworthiness contract lives
  (never guess, always confirm before writing, no medical advice, honest human handoff).
- **LangGraph graphs** (`graphs/`): deterministic state machines, no LLM node. Each write
  operation is `validate_and_stage → wait_for_confirmation → commit_or_abort`, persisted via a
  Postgres-backed checkpointer so state survives across two separate tool calls with a live
  voice turn in between.
- **Repositories** (`db/repositories/`): plain async SQLAlchemy queries for everything
  read-only (catalog lookups, report status, lab info).

## Project layout

```
├── data.json                  # real seed data: lab info, tests, packages, offers, symptom routing
├── db/
│   ├── schema.sql              # Postgres DDL
│   ├── apply_schema.py         # applies schema.sql
│   └── seed.py                 # loads data.json + sample patients/reports/appointments
├── src/receptionist/
│   ├── config.py                # env-driven Settings (agent name, models, log level, ...)
│   ├── instructions.py          # voice-layer + reasoning-layer prompts
│   ├── agent.py                 # ReceptionistAgent + GPTLiveModel wiring
│   ├── worker.py                # LiveKit worker entrypoint
│   ├── observability.py         # tokens/latency/errors/cost tracking
│   ├── validation.py            # phone number / date-of-birth validation
│   ├── call_state.py            # per-call state (identified patient, pending action)
│   ├── db/                      # SQLAlchemy models + repositories
│   ├── graphs/                  # propose/confirm state machines (registration, booking, ...)
│   └── tools/                   # @function_tool functions GPT-Live actually calls
├── server/token_server.py     # FastAPI: mints LiveKit join tokens, serves branding
├── web/                        # browser demo (index.html + app.js, livekit-client via CDN)
├── scripts/
│   ├── check_gpt_live_access.py # verifies the OpenAI account has GPT-Live access
│   ├── setup_checkpointer.py    # one-time LangGraph checkpointer table setup
│   └── usage_report.py          # prints tokens/cost/latency/errors from call_events
├── tests/                      # pytest: graph guardrail tests + tool smoke tests
├── run.py                      # alternative: runs worker/token/web as local processes, Docker infra separate
├── Dockerfile                  # image for the worker, token server, and web services below
└── docker-compose.yml          # Postgres, Adminer, self-hosted LiveKit, and the app's worker/token/web
```

## Prerequisites

- Python 3.11+
- Docker Desktop
- An OpenAI API key with GPT-Live access (`OPENAI_API_KEY`)

## Setup

```powershell
# 1. Copy the env template and fill in OPENAI_API_KEY (and anything else you want to change)
copy .env.example .env

# 2. Start Postgres, LiveKit, and Adminer
docker compose up -d postgres adminer livekit

# 3. Apply the schema and seed real lab data from data.json, and set up the
#    LangGraph checkpointer tables -- run these from a virtualenv (below) or
#    via `docker compose run --rm worker python <script>` if you'd rather not
#    set up Python locally.
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
$env:PYTHONPATH="src"; python db/apply_schema.py
$env:PYTHONPATH="src"; python db/seed.py
$env:PYTHONPATH="src"; python scripts/setup_checkpointer.py
```

## Running the demo

**Option A — fully in Docker**

```powershell
docker compose up -d
```

Builds and starts everything: Postgres, LiveKit, Adminer, the agent worker, the token
server, and the web page's static server. The repo is bind-mounted into the containers, so
code edits on the host apply on the next request/restart without rebuilding the image.

```powershell
docker compose logs -f worker token web   # follow app logs
docker compose down                       # stop everything (add -v to also wipe the DB volume)
```

> The `worker` service shares LiveKit's network namespace (`network_mode: "service:livekit"`)
> rather than joining the network normally. That's deliberate: the worker does real WebRTC
> audio, and `livekit.yaml`'s `node_ip: 127.0.0.1` (the fix for a "connects, then drops after
> 30s" bug) only works when the worker sees the same loopback as the LiveKit server. Don't
> change this without re-verifying a live call still holds for more than 30 seconds.

**Option B — Python processes locally, Docker only for infra**

```powershell
.venv\Scripts\python run.py
```

Brings up Postgres/LiveKit/Adminer via Docker (if not already running), then starts the
agent worker, the token server, and the web page's static server as local processes,
streaming all their output together. Press `Ctrl+C` to stop the three app processes (Docker
containers are left running).

**Option C — manual, separate terminals** (useful for isolating which process is doing what)

```powershell
# Terminal 1 — agent worker
.venv\Scripts\python -m receptionist.worker dev

# Terminal 2 — token server
.venv\Scripts\python -m uvicorn server.token_server:app --host 127.0.0.1 --port 8080

# Terminal 3 — web page
cd web
python -m http.server 5500
```

Whichever option you use, open **http://localhost:5500**, enter a phone number, and start the call.

## Configuration

All configuration lives in `.env` (see `.env.example` for the full list with comments):

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Needs GPT-Live alpha access |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit project (self-hosted via Docker by default) |
| `DATABASE_URL` / `CHECKPOINTER_DATABASE_URL` | Postgres, two DSN forms (asyncpg for the app, psycopg for the LangGraph checkpointer) |
| `AGENT_NAME` | The agent's spoken persona name — never hardcoded in code |
| `REASONING_MODEL` | GPT-Live's backend reasoning model (picks tools) |
| `LOG_LEVEL` | Worker log level — `dev` mode defaults to `DEBUG` if unset, which is noisy enough to stall responses when piped through `run.py` |
| `COST_RATES` | Optional, JSON — per-model billing rates for cost estimation (see Observability below) |

Lab name, address, phone, hours, and accreditations are **not** env vars — they come from the
`lab_info` table (seeded from `data.json`), so re-skinning for a different lab is a data change.

## Observability

Every call records token usage, per-turn latency, errors, and close reason to the
`call_events` table (see `observability.py`). After some calls have happened:

```powershell
$env:PYTHONPATH="src"; python scripts/usage_report.py --since-hours 24
```

Prints call count, estimated cost (from `COST_RATES`, $0 for any model with no rate
configured — costs are never fabricated), tokens by model, average/p95 response latency, and
recent errors.

## Testing

```powershell
$env:PYTHONPATH="src"; python -m pytest -q
```

Tests run against the real Postgres database (via Docker) and directly exercise each
propose/confirm LangGraph — asserting zero database writes happen before confirmation, and a
correct write happens after.

## Real phone line (not wired up yet)

The architecture supports it without changing `agent.py`, `tools/`, or `graphs/` — a SIP call
just produces a `JobContext` with a SIP participant instead of a browser one, dispatched to
the same `entrypoint`. Requires a SIP trunk provider (e.g. Twilio Elastic SIP Trunking) and a
LiveKit SIP trunk + dispatch rule, both manual/credentialed setup steps.

## Known gaps

- Real phone/SIP line is designed for but not wired up.
- Appointment slot capacity uses a simple constant-capacity heuristic, not a dedicated
  slots/capacity table.
- Browser demo has no real caller ID — the agent always asks for name + phone/DOB verbally.