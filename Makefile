# Common local tasks. Run `make` or `make help` to list them.
.DEFAULT_GOAL := help
.PHONY: help up down logs reset test test-web test-backend smoke import-jobs replay-jobs reset-demo

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
	docker compose run --rm --no-deps -e RUN_DB_INTEGRATION=1 -v "$(CURDIR)/backend/tests:/app/tests:ro" api \
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
