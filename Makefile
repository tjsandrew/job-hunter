# Common local tasks. Run `make` or `make help` to list them.
.DEFAULT_GOAL := help
.PHONY: help up down logs reset test test-web test-backend smoke import-jobs replay-jobs reset-demo embedder-up embedder-down test-embedder backfill

help: ## List available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-14s %s\n", $$1, $$2}'

up: ## Build and start the local stack (http://localhost:5173)
	docker compose up --build -d

down: ## Stop the stack, keeping data
	docker compose stop

logs: ## Show recent API and web logs
	docker compose logs --tail=100 api web

reset: ## DELETE the local database and documents, then restart
	docker compose down --volumes
	docker compose up --build -d

test: test-web test-backend smoke ## Run all checks (stack must be running)

test-web: ## Frontend unit tests and production build
	cd apps/web && npm ci && npm test && npm run build

test-backend: ## Backend unit and PostgreSQL integration tests
	docker compose run --rm --no-deps -e RUN_DB_INTEGRATION=1 -v "$(CURDIR)/backend/tests:/app/tests:ro" -v "$(CURDIR)/contracts:/app/contracts:ro" api \
		sh -c 'pip install -c requirements.lock ".[test]" && pytest /app/tests -q'

smoke: ## HTTP smoke test against the running API
	python3 scripts/smoke.py

import-jobs: ## Import live Singapore jobs (manual, one-shot)
	docker compose exec api python -m job_hunter.import_jobs --greenhouse stripe --greenhouse cloudflare \
		--greenhouse coinbase --lever lalamove --location Singapore

replay-jobs: ## Re-import the last saved job snapshot without contacting sources
	docker compose exec api python -m job_hunter.import_jobs \
		--snapshot-in /data/job-import-snapshots/latest.json --location Singapore

reset-demo: ## Reset Alice's demo profile, resume and application
	docker compose run --rm --no-deps -v "$(CURDIR)/backend/src:/app/src:ro" \
		-v "$(CURDIR)/scripts/setup_demo_workspace.py:/app/setup_demo_workspace.py:ro" \
		-e PYTHONPATH=/app/src api python /app/setup_demo_workspace.py

embedder-up: ## Build and start the embedder service (http://localhost:8100); `make up` already starts it
	docker compose up --build -d embedder

embedder-down: ## Stop the embedder service
	docker compose stop embedder

backfill: ## Embed open jobs and each user's confirmed profile (idempotent; needs the embedder running)
	docker compose run --rm --no-deps api python -m job_hunter.embedding.backfill

test-embedder: ## Embedder contract tests (fake backend, no model needed)
	docker compose run --rm --no-deps --user root -e EMBEDDER_SERVICE_BACKEND=fake \
		-v "$(CURDIR)/services/embedder/tests:/app/tests:ro" embedder \
		sh -c 'pip install -q -c requirements.lock pytest httpx && pytest /app/tests -q -p no:cacheprovider'

openapi: ## Regenerate the committed OpenAPI contract from current backend source
	@mkdir -p contracts
	docker compose run --rm --no-deps -T -v "$(CURDIR)/backend/src:/app/src:ro" -e PYTHONPATH=/app/src api python -c 'import json; from job_hunter.api.main import app; print(json.dumps(app.openapi(), sort_keys=True, indent=2))' > contracts/openapi.json
