.PHONY: help build start stop status logs clean test lint

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

build: ## Build all Docker images
	docker compose build

start: ## Start the full BVR Nexus stack
	chmod +x start.sh && ./start.sh

stop: ## Stop all services
	docker compose down

dev: ## Start in development mode (with hot reload)
	BVR_ENV=dev docker compose up -d bvr-api workers

status: ## Check system status
	python -m bvr_cli.main status

logs: ## Tail logs from all services
	docker compose logs -f

logs-api: ## Tail BVR API logs
	docker compose logs -f bvr-api

logs-workers: ## Tail worker logs
	docker compose logs -f bvr-workers

clean: ## Remove all containers, volumes, and data
	docker compose down -v
	docker system prune -f

test: ## Run all tests
	pytest tests/ -v --tb=short

test-integration: ## Run integration tests
	pytest tests/integration/ -v --tb=short

lint: ## Run linting on all Python code
	ruff check .
	black --check .
	mypy .

format: ## Format all Python code
	ruff check . --fix
	black .

security: ## Run security audit
	bandit -r .
	safety check

keycloak-setup: ## Initialize Keycloak realm and client
	@echo "Setting up Keycloak..."
	@sleep 10
	@python scripts/setup_keycloak.py

vault-setup: ## Initialize Vault and enable KV v2
	@echo "Setting up Vault..."
	@sleep 5
	@python scripts/setup_vault.py

backup: ## Backup PostgreSQL and MinIO
	@mkdir -p backups/$$(date +%Y%m%d)
	docker exec bvr-postgres pg_dump -U bvr bvr_nexus > backups/$$(date +%Y%m%d)/postgres.sql
	@echo "Backup complete: backups/$$(date +%Y%m%d)/"


secrets: ## Generate strong secrets in .env file
	@echo "🔐 Generating secrets..."
	@python3 -c "
import secrets
import os

env_file = '.env'
if not os.path.exists(env_file):
    open(env_file, 'w').close()

with open(env_file, 'r') as f:
    lines = f.readlines()

secrets_map = {}
for line in lines:
    if '=' in line and not line.startswith('#'):
        key, val = line.strip().split('=', 1)
        if val.strip() == 'GENERATE':
            secrets_map[key] = secrets.token_urlsafe(32)

with open(env_file, 'w') as f:
    for line in lines:
        if '=' in line and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            if key in secrets_map:
                f.write(f'{key}={secrets_map[key]}\n')
            else:
                f.write(line)
        else:
            f.write(line)

for key, val in secrets_map.items():
    print(f'  🔑 Generated {key}')

print('✅ Secrets generated in .env')
"
