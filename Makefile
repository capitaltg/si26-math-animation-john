# Convenience wrappers around docker compose. Every target is idempotent
# unless documented otherwise. Run `make help` for the full list.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Compose project name — normalized as Docker Compose itself does: lowercase,
# keep [a-z0-9_-] only. Pinned + exported so every `docker compose` call in
# this Makefile targets the same project, and so `docker ps` label filters
# can be by-value (not just by-key, which would match every project's
# containers).
export COMPOSE_PROJECT_NAME := $(shell basename $(CURDIR) | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')

COMPOSE_BASE := docker compose
COMPOSE_DEV  := $(COMPOSE_BASE) -f docker-compose.yml -f docker-compose.dev.yml
COMPOSE_TLS  := $(COMPOSE_BASE) -f docker-compose.yml -f docker-compose.tls.yml

.PHONY: help
help:  ## show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nTargets:\n"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- lifecycle ---------------------------------------------------------------

.PHONY: env
env:  ## create .env from example if it does not exist yet
	@test -f .env || cp .env.docker.example .env
	@echo ".env ready — open it and fill in AWS_* and POSTGRES_PASSWORD"

.PHONY: build
build: env  ## build all images (prod)
	$(COMPOSE_BASE) build

.PHONY: up
up: env  ## start the production stack (HTTP :80)
	$(COMPOSE_BASE) up -d
	@echo "→ http://localhost"

# Tear-down order matters: overlays first so no service holds the shared
# network open. `--remove-orphans` covers profile-gated services (meta-worker,
# frontend-dev, caddy) that the base command wouldn't see.
.PHONY: down
down:  ## stop the stack (keep volumes)
	-$(COMPOSE_TLS) down --remove-orphans
	-$(COMPOSE_DEV) down --remove-orphans
	$(COMPOSE_BASE) down --remove-orphans

.PHONY: nuke
nuke:  ## stop the stack AND delete volumes (Postgres, Redis, media)
	-$(COMPOSE_TLS) down -v --remove-orphans
	-$(COMPOSE_DEV) down -v --remove-orphans
	$(COMPOSE_BASE) down -v --remove-orphans

.PHONY: logs
logs:  ## tail logs from all services
	$(COMPOSE_BASE) logs -f

.PHONY: ps
ps:  ## show container status
	$(COMPOSE_BASE) ps

# Only backend + (if it's running) meta-worker consume BEDROCK_*, MEDIA_*,
# CORS_*, etc. — nginx and Caddy have no env-driven config, so touching
# them here would collide with Caddy's :80 under the TLS overlay for no
# benefit. Meta-worker is profile-gated, so it must be brought up with
# `--profile meta` to be visible to compose.
#
# Detect which overlay is currently active by checking for
# overlay-exclusive containers (frontend-dev = dev, caddy = tls). Restarting
# with the wrong compose invocation would drop bind mounts, hot-reload, and
# ports for a dev backend, or refuse to boot under TLS.
.PHONY: restart
restart:  ## recreate services that consume .env (backend + meta-worker if running); works under base, dev, or tls overlay
	@# Detect the active overlay via the compose service label on any
	@# running container of THIS project — `compose ps` from the wrong
	@# compose invocation won't see services declared only in an overlay,
	@# but `docker ps` sees every container regardless of how it was
	@# launched. Filter by project=$(COMPOSE_PROJECT_NAME) so an unrelated
	@# repo's frontend-dev/caddy/meta-worker can't steer us.
	@proj_filter="label=com.docker.compose.project=$(COMPOSE_PROJECT_NAME)"; \
	if docker ps --filter "$$proj_filter" --filter "label=com.docker.compose.service=frontend-dev" --format '{{.ID}}' | grep -q .; then \
	  compose="$(COMPOSE_DEV)"; echo "dev overlay detected — recreating via docker-compose.dev.yml"; \
	elif docker ps --filter "$$proj_filter" --filter "label=com.docker.compose.service=caddy" --format '{{.ID}}' | grep -q .; then \
	  compose="$(COMPOSE_TLS)"; echo "TLS overlay detected — recreating via docker-compose.tls.yml"; \
	else \
	  compose="$(COMPOSE_BASE)"; echo "no overlay detected — recreating via base compose"; \
	fi; \
	$$compose up -d --force-recreate --no-deps backend; \
	if docker ps --filter "$$proj_filter" --filter "label=com.docker.compose.service=meta-worker" --format '{{.ID}}' | grep -q .; then \
	  echo "meta-worker running — recreating it too"; \
	  $$compose --profile meta up -d --force-recreate --no-deps meta-worker; \
	fi

# --- dev ---------------------------------------------------------------------

.PHONY: dev
dev: env  ## dev stack: backend hot-reload + vite dev + postgres + redis
	$(COMPOSE_DEV) --profile dev up -d
	@echo "→ frontend http://localhost:5173"
	@echo "→ backend  http://localhost:8000"

.PHONY: frontend
frontend: env  ## dev vite server ONLY (backend still needed — start with 'make dev' first, or point vite at a remote backend)
	$(COMPOSE_DEV) --profile frontend up -d frontend-dev
	@echo "→ frontend http://localhost:5173"

.PHONY: dev-logs
dev-logs:  ## tail dev logs
	$(COMPOSE_DEV) logs -f

.PHONY: dev-down
dev-down:  ## stop dev stack
	$(COMPOSE_DEV) down --remove-orphans

# --- tls ---------------------------------------------------------------------

.PHONY: tls
tls: env  ## production stack behind Caddy (TLS on :443). Requires DOMAIN + TLS_EMAIL in .env
	@grep -q '^DOMAIN=' .env && grep -q '^TLS_EMAIL=' .env || { echo "DOMAIN and TLS_EMAIL must be set in .env"; exit 2; }
	$(COMPOSE_TLS) up --build -d
	@echo "→ https://$$(grep '^DOMAIN=' .env | cut -d= -f2)"

.PHONY: tls-logs
tls-logs:  ## tail TLS-stack logs (Caddy + nginx + backend)
	$(COMPOSE_TLS) logs -f

# --- ops ---------------------------------------------------------------------

.PHONY: migrate
migrate:  ## run alembic upgrade head against the running Postgres
	$(COMPOSE_BASE) exec backend alembic upgrade head

.PHONY: shell
shell:  ## drop into a shell inside the backend container
	$(COMPOSE_BASE) exec backend bash

.PHONY: psql
psql:  ## psql client into the postgres container
	$(COMPOSE_BASE) exec postgres psql -U demo demo

.PHONY: backup
backup:  ## dump Postgres to demo-YYYY-MM-DD.sql.gz in the current directory
	$(COMPOSE_BASE) exec -T postgres pg_dump -U demo demo | gzip > demo-$$(date -u +%F).sql.gz
	@ls -lh demo-$$(date -u +%F).sql.gz

# --- ci ---------------------------------------------------------------------

# `set -e` + trap: if any curl/health step fails the trap fires `down` so a
# broken run does not leave the stack half-up.
.PHONY: smoke
smoke: env  ## bring up prod, hit /healthz, tear down (always)
	@set -e; \
	trap '$(COMPOSE_BASE) down --remove-orphans' EXIT; \
	$(COMPOSE_BASE) up -d; \
	echo "waiting for backend to become healthy..."; \
	for i in $$(seq 1 60); do \
	  s=$$($(COMPOSE_BASE) ps --format json backend 2>/dev/null | grep -o '"Health":"healthy"' || true); \
	  if [ -n "$$s" ]; then echo "healthy"; break; fi; \
	  sleep 2; \
	done; \
	curl -fsS http://localhost/healthz && echo

# lint-compose must NOT mutate the operator's .env. Docker compose needs an
# .env file to exist because services declare `env_file: .env`; we work in a
# temp directory whose only role is to hold an empty .env, and inject the
# required substitution values via the shell environment (compose reads
# shell env BEFORE .env, so the empty file is fine).
.PHONY: lint-compose
lint-compose:  ## validate every compose overlay (no side effects on .env)
	@set -e; \
	tmp=$$(mktemp -d); \
	trap 'rm -rf $$tmp' EXIT; \
	touch $$tmp/.env; \
	env_vars="POSTGRES_PASSWORD=ci_dummy DOMAIN=demo.example.com TLS_EMAIL=demo@example.com"; \
	for files in "-f $(PWD)/docker-compose.yml" \
	             "-f $(PWD)/docker-compose.yml -f $(PWD)/docker-compose.dev.yml" \
	             "-f $(PWD)/docker-compose.yml -f $(PWD)/docker-compose.tls.yml"; do \
	  (cd $$tmp && env $$env_vars docker compose $$files config --quiet) || exit 1; \
	done; \
	echo "base + dev + tls: OK"
