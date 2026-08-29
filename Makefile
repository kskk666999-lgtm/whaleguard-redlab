PYTHON ?= python3
NPM ?= npm
COMPOSE ?= docker compose

.PHONY: init dev test lint format seed reset docker-up docker-down compose-check verify

init:
	$(PYTHON) scripts/bootstrap_env.py

dev: init
	$(COMPOSE) up --build

test:
	$(PYTHON) scripts/validate_test_cases.py
	$(PYTHON) scripts/validate_compose.py
	cd packages/policy-engine && $(PYTHON) -m pytest -q
	cd apps/worker && $(PYTHON) -m pytest -q
	cd apps/api && $(PYTHON) -m pytest -q
	cd labs/mock-llm && $(PYTHON) -m pytest -q
	cd labs/mock-agent && $(PYTHON) -m pytest -q
	cd labs/mock-mcp-server && $(PYTHON) -m pytest -q
	$(PYTHON) scripts/test_migrations.py
	cd apps/web && $(NPM) test

lint:
	$(PYTHON) -m ruff check apps packages labs scripts
	cd apps/web && $(NPM) run lint
	cd apps/web && $(NPM) run typecheck

format:
	$(PYTHON) -m ruff format apps packages labs scripts
	$(PYTHON) -m ruff check --fix apps packages labs scripts
	cd apps/web && $(NPM) run lint -- --fix

seed:
	$(PYTHON) scripts/seed_demo.py

reset:
	$(PYTHON) scripts/reset_dev.py
	$(PYTHON) scripts/seed_demo.py

docker-up: init
	$(COMPOSE) up -d --build

docker-down:
	$(COMPOSE) down

compose-check:
	$(COMPOSE) config --quiet

verify: lint test
	cd apps/web && $(NPM) run build
	cd apps/web && $(NPM) run test:e2e
	$(COMPOSE) config --quiet
