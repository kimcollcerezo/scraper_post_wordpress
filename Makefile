# Makefile — Despertare Migration Engine

AGENT_DIR := packages/migration-agent
PYTHON    := python3

.PHONY: setup lint format test dry-run validate clean-artifacts help

help:
	@echo "Targets disponibles:"
	@echo "  make setup           — Instal·la dependències del migration-agent"
	@echo "  make lint            — Executa ruff lint"
	@echo "  make format          — Executa ruff format"
	@echo "  make test            — Executa pytest"
	@echo "  make dry-run         — Dry-run amb source=wordpress-main, limit=10"
	@echo "  make validate        — Valida snapshots existents"
	@echo "  make clean-artifacts — Elimina artifacts de runs anteriors"

setup:
	cd $(AGENT_DIR) && pip install -e ".[dev]"

lint:
	cd $(AGENT_DIR) && ruff check migration_agent tests

format:
	cd $(AGENT_DIR) && ruff format migration_agent tests

test:
	cd $(AGENT_DIR) && pytest tests/ -v

dry-run:
	cd $(AGENT_DIR) && $(PYTHON) -m migration_agent.cli --mode dry-run --source wordpress-main --limit 10

validate:
	cd $(AGENT_DIR) && $(PYTHON) -m migration_agent.cli --mode validate --source wordpress-main

clean-artifacts:
	@echo "Eliminant artifacts..."
	rm -rf artifacts/import-batches/*
	rm -rf artifacts/snapshots/*
	rm -rf artifacts/seo/*
	@echo "Artifacts eliminats."
