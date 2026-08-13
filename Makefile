# Convenience wrappers around docker compose. Every target is idempotent
# unless documented otherwise. Run `make help` for the full list.

SHELL := /bin/bash
.DEFAULT_GOAL := help

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

.PHONY: down
down:  ## stop the stack (keep volumes)
	$(COMPOSE_BASE) down
	-$(COMPOSE_DEV) down
	-$(COMPOSE_TLS) down

.PHONY: nuke
nuke:  ## stop the stack AND delete volumes (Postgres, Redis, media)
	$(COMPOSE_BASE) down -v
	-$(COMPOSE_DEV) down -v
	-$(COMPOSE_TLS) down -v

.PHONY: logs
logs:  ## tail logs from all services
	$(COMPOSE_BASE) logs -f

.PHONY: ps
ps:  ## show container status
	$(COMPOSE_BASE) ps

.PHONY: restart
restart:  ## restart backend + nginx (picks up .env changes)
	$(COMPOSE_BASE) restart backend nginx

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
	$(COMPOSE_DEV) down

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

.PHONY: smoke
smoke: env  ## bring up prod, hit /healthz, tear down
	$(COMPOSE_BASE) up -d
	@echo "waiting for backend to become healthy..."
	@for i in $$(seq 1 60); do \
	  s=$$($(COMPOSE_BASE) ps --format json backend 2>/dev/null | grep -o '"Health":"healthy"' || true); \
	  if [ -n "$$s" ]; then echo "healthy"; break; fi; \
	  sleep 2; \
	done
	@curl -fsS http://localhost/healthz && echo
	$(COMPOSE_BASE) down

.PHONY: lint-compose
lint-compose: env  ## validate every compose overlay
	$(COMPOSE_BASE) config --quiet
	$(COMPOSE_DEV)  config --quiet
	@grep -q '^DOMAIN=' .env || echo "DOMAIN=example.com" >> .env
	@grep -q '^TLS_EMAIL=' .env || echo "TLS_EMAIL=demo@example.com" >> .env
	$(COMPOSE_TLS)  config --quiet
