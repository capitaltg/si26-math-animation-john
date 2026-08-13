# Deploy — Docker

This is the reference for standing the demo up from scratch on a new machine.
Read it top-to-bottom the first time; the checklists at the end are for return
visits.

- [Prereqs](#prereqs)
- [Bring up (HTTP, single host)](#bring-up-http-single-host)
- [Bring up (public URL with TLS)](#bring-up-public-url-with-tls)
- [Environment variables](#environment-variables)
- [Rate-limit / cost controls](#rate-limit--cost-controls)
- [Kill switch](#kill-switch)
- [Operations](#operations)
- [Troubleshooting](#troubleshooting)
- [Development mode](#development-mode)

---

## Prereqs

- Docker Engine ≥ 24 and Docker Compose ≥ 2.24 (older Compose does not honor
  the `!reset` YAML tag used by the TLS overlay). Docker Desktop on macOS or
  Windows both include a compose that satisfies this.
- ~4 GB free disk for the images (the backend base ships manim + LaTeX and is
  ~3.5 GB uncompressed).
- An AWS IAM access key that can call Bedrock in your chosen region.

The stack ships as five services (nginx, backend, postgres, redis, and an
optional meta-worker) plus an optional Caddy front for TLS.

```
public → [Caddy :443]* → nginx :80 → backend :8000 → { postgres, redis }
                                    ↘ meta-worker (opt-in profile)
* TLS overlay only
```

---

## Bring up (HTTP, single host)

Suitable for a laptop demo, an internal VPN URL, or as a smoke test before
adding TLS.

```bash
git clone https://github.com/capitaltg/si26-math-animation-john.git
cd si26-math-animation-john

cp .env.docker.example .env
# open .env in your editor and fill in the REPLACE_ME values (see below)

docker compose up --build -d
# → http://localhost   (or the machine's LAN IP)
```

`alembic upgrade head` runs automatically on backend startup; you do not need
to run it by hand. `nginx` will wait until the backend reports healthy before
it starts serving, so the first request never hits a 502 during boot.

### Minimum .env for a local HTTP demo

```dotenv
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6

BEDROCK_DAILY_CALL_CAP=2000
BEDROCK_PER_IP_HOURLY_CAP=40

POSTGRES_PASSWORD=change_me_to_a_long_random_string
```

Everything else has a safe default in `.env.docker.example`.

---

## Bring up (public URL with TLS)

Caddy fronts nginx, auto-provisions a Let's Encrypt certificate for your
domain, and forwards internal traffic. The base nginx port stops being
published so Caddy owns 80/443.

Requirements:

- A DNS `A`/`AAAA` record for `DOMAIN` pointing at this host.
- Ports 80 **and** 443 reachable from the internet (80 is required for the
  ACME HTTP-01 challenge).

```bash
# in .env, additionally set:
DOMAIN=demo.example.com
TLS_EMAIL=you@example.com
SESSION_COOKIE_SECURE=true         # now safe — TLS in front

docker compose \
  -f docker-compose.yml \
  -f docker-compose.tls.yml \
  up --build -d
# → https://demo.example.com
```

Caddy's storage lives in the `caddy_data` volume, so the issued certificate
survives redeploys.

If you want to test issuance without burning Let's Encrypt production rate
limits, uncomment the `acme_ca` line in `Caddyfile` to point at the staging
endpoint first.

---

## Environment variables

Full list, with defaults. `.env.docker.example` is the source of truth — this
table is a summary.

| Variable | Default | What it does |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Region for the Bedrock client. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | – | IAM credentials for Bedrock. |
| `AWS_SESSION_TOKEN` | – | Set if using temporary creds. |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Bedrock model id. |
| `BEDROCK_DISABLED` | `0` | Kill switch — see [Kill switch](#kill-switch). |
| `BEDROCK_DAILY_CALL_CAP` | `0` (off) | Global calls per UTC day allowed. `0` disables L3. |
| `BEDROCK_PER_IP_HOURLY_CAP` | `0` (off) | Per-client-IP calls per hour. `0` disables L2. |
| `META_TEMPLATES_ENABLED` | `false` | Enable the meta-template teacher API. |
| `META_CODEGEN_ENABLED` | `false` | Enable the meta-template code generator (needed for `meta-worker`). |
| `META_APPROVAL_ENABLED` | `false` | Enable the meta-template approval gate. |
| `META_DYNAMIC_CLASSIFIER_ENABLED` | `false` | Enable dynamic template classifier. |
| `META_REVIEWER_TOKEN` | – | Admin bearer for the review API — required when `META_APPROVAL_ENABLED=true`. |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` only when TLS terminates in front. |
| `MEDIA_MAX_BYTES` | `5368709120` (5 GiB) | Global cap on rendered media on disk. `0` disables. |
| `MEDIA_SWEEP_INTERVAL_SECONDS` | `300` | How often to enforce the cap. Must be `>0` when `MEDIA_MAX_BYTES>0`. |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173` | Comma-separated CORS whitelist. |
| `MATH_ANIM_MOCK_BEDROCK` | – | `1` returns canned Bedrock responses — CI/smoke only. |
| `POSTGRES_PASSWORD` | – | Password for the Postgres role `demo`. |
| `PUBLIC_HTTP_PORT` | `80` | Base nginx published port (only used without the TLS overlay). |
| `DOMAIN` | – | TLS overlay only: public FQDN Caddy issues a cert for. |
| `TLS_EMAIL` | – | TLS overlay only: email address on the Let's Encrypt account. |

---

## Rate-limit / cost controls

Four independent layers guard the Bedrock spend. All are configured via
`.env`.

- **L1 — nginx `limit_req`** (always on). Per-client-IP HTTP rate limit,
  configured in `nginx/nginx.conf`. Bedrock-heavy endpoints (`/upload`,
  `/options`, `/storyboard`, `/meta`) use a strict `2 r/s` zone with burst
  5; static / media endpoints use a generous `30 r/s` zone.

- **L2 — per-IP Bedrock cap** (`BEDROCK_PER_IP_HOURLY_CAP`). Redis counter
  keyed by client IP, TTL = end-of-hour. The 429 response includes
  `Retry-After`.

- **L3 — global daily Bedrock cap** (`BEDROCK_DAILY_CALL_CAP`). Redis
  counter keyed by UTC day, TTL = end-of-day + 60s. Persistent — the counter
  survives Redis restarts (AOF is on and mounted to a named volume).

- **L0 — kill switch** (`BEDROCK_DISABLED`). Highest priority; short-circuits
  every Bedrock call to a `503`. Set it when you need to stop spend without
  redeploying.

Both L2 and L3 fail closed when Redis is unreachable **and** a cap is set:
the backend returns `503` rather than let calls hit AWS unmetered. When both
caps are `0`, the guards are entirely opt-out and Redis is not required.

There is no code-level cap on tokens or dollars — the limits are
invocation-count. If you need a spend estimate, multiply by your model's
per-call price.

---

## Kill switch

To stop all Bedrock calls immediately:

```bash
# edit .env and set BEDROCK_DISABLED=1
docker compose restart backend
# (only include meta-worker in the restart if META_CODEGEN_ENABLED=true)
```

Every Bedrock call will now return `503 AI features are temporarily disabled`.
Flip it back to `0` and restart to resume.

---

## Operations

### Watch logs

```bash
docker compose logs -f backend               # backend only
docker compose logs -f                        # everything
```

### Restart just one service

```bash
docker compose restart backend
docker compose restart nginx
```

### Redeploy after a code change

```bash
git pull
docker compose build backend nginx
docker compose up -d
```

The backend runs `alembic upgrade head` on boot, so DB migrations apply
automatically.

### Enable the meta-worker

By default the meta-template subsystem is disabled and the worker service
is under the `meta` compose profile so it doesn't restart-loop.

```bash
# in .env
META_TEMPLATES_ENABLED=true
META_CODEGEN_ENABLED=true
# (set META_APPROVAL_ENABLED / META_REVIEWER_TOKEN too if you want the review API)

docker compose --profile meta up -d
```

### Back up

The stateful volumes are `postgres_data`, `redis_data`, `backend_media`, and
`backend_var`. A minimal backup:

```bash
docker compose exec -T postgres pg_dump -U demo demo | gzip > demo-$(date -u +%F).sql.gz
```

For a full-fidelity snapshot, stop the stack and archive the volume mount
points (`docker volume inspect`), or run a tool like `restic` against them.

### Tear down

```bash
docker compose down          # keep volumes
docker compose down -v       # nuke volumes (Postgres, Redis, media, var)
```

---

## Troubleshooting

**`docker compose config` warns "POSTGRES_PASSWORD is not set"**
You haven't copied `.env.docker.example` to `.env` yet, or the file doesn't
have `POSTGRES_PASSWORD=…`. Fix that first.

**Backend container flips between `starting` and `unhealthy`**
Check the log: `docker compose logs backend`. Most common cause is an
`alembic upgrade head` failure — you'll see a Postgres error at the top.

**Nginx returns `502 Bad Gateway`**
The backend isn't healthy yet. Wait a few seconds and retry; if it persists,
`docker compose logs backend`.

**Every request returns `429`**
You've tripped an L1 zone (see `nginx/nginx.conf`). Look at the nginx log:
`docker compose logs nginx | grep 429`. The `Retry-After` header on the
response tells the client when to try again.

**Every AI call returns `503 temporarily disabled`**
Kill switch is on. Check `.env` for `BEDROCK_DISABLED=1` and clear it if you
didn't mean to.

**Every AI call returns `503 temporarily unavailable`**
Rate-limit backend (Redis) is unreachable while a cap is set. Check
`docker compose ps redis` and `docker compose logs redis`. The backend
fails closed on purpose so calls don't slip past unmetered.

**Certificate not issuing under the TLS overlay**
- DNS: `dig +short A demo.example.com` must return your host.
- Ports 80 and 443 must both be reachable from the internet — the ACME
  HTTP-01 challenge uses port 80.
- Watch: `docker compose -f docker-compose.yml -f docker-compose.tls.yml logs -f caddy`.
- If you're rate-limited by Let's Encrypt, switch to their staging endpoint
  (uncomment `acme_ca` in `Caddyfile`) until issuance works, then switch
  back.

**Per-IP quota collapses when behind a load balancer / Cloudflare**
The `$remote_addr` nginx sees becomes the LB, so every user shares one IP
in the quota. Fix by dropping a `set_real_ip_from` snippet into
`nginx/trusted-proxies.d/` and rebuilding the nginx image. The TLS overlay
ships one for Caddy as a template.

---

## Development mode

For hot-reload backend + frontend without rebuilding the image, see the
`docker-compose.dev.yml` overlay and the top-level `Makefile`:

```bash
make dev         # backend hot-reload + vite dev server + postgres + redis
make frontend    # vite dev only, assumes backend at localhost:8000
make down        # stop everything
make help        # list all targets
```

`make dev` bind-mounts the source tree into the containers, so a save
triggers uvicorn reload and vite HMR without a rebuild. Postgres and Redis
still run in containers; media, `.venv`, and `node_modules` are excluded
from the mount so the container's own copies stay intact.

For running the full test suite locally without Docker, see the paths
documented in `README.md`.
