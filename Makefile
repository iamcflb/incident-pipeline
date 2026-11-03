# Makefile for Agent Architecture

.PHONY: help install test lint typecheck build build-all docker-build docker-push deploy-dev deploy-prod clean

# Default target
help:
	@echo "Agent Architecture - Micro-agentes para Classificação de Incidentes"
	@echo ""
	@echo "Targets:"
	@echo "  install       - Instala dependências de todos os agentes"
	@echo "  test          - Roda todos os testes"
	@echo "  test-<agent>  - Roda testes de um agente específico (redator, triador, especialista, handoff)"
	@echo "  lint          - Roda ruff em todo o código"
	@echo "  typecheck     - Roda mypy em todo o código"
	@echo "  build         - Build local de todas as imagens Docker"
	@echo "  docker-build  - Build multi-arch para registry"
	@echo "  docker-push   - Push para registry"
	@echo "  deploy-dev    - Deploy no cluster dev (kind/k3d)"
	@echo "  deploy-prod   - Deploy no cluster prod"
	@echo "  clean         - Remove artefatos de build"
	@echo "  adr           - Lista ADRs"

# ===================== Installation =====================
install:
	@echo "Installing shared library..."
	cd shared && pip install -e ".[dev]"
	@echo "Installing redator..."
	cd agents/redator && pip install -e ".[dev]" --no-deps
	@echo "Installing triador..."
	cd agents/triador && pip install -e ".[dev]" --no-deps
	@echo "Installing especialista..."
	cd agents/especialista && pip install -e ".[dev]" --no-deps
	@echo "Installing handoff..."
	cd agents/handoff && pip install -e ".[dev]" --no-deps

# ===================== Testing =====================
test: test-shared test-redator test-triador test-especialista test-handoff

test-shared:
	cd shared && pytest tests -v --cov=agent_shared

test-redator:
	cd agents/redator && pytest tests -v --cov=redator

test-triador:
	cd agents/triador && pytest tests -v --cov=triador

test-especialista:
	cd agents/especialista && pytest tests -v --cov=especialista

test-handoff:
	cd agents/handoff && pytest tests -v --cov=handoff

# ===================== Linting & Type Checking =====================
lint:
	ruff check shared/src agents/*/src agents/*/tests

typecheck:
	mypy shared/src agents/redator/src agents/triador/src agents/especialista/src agents/handoff/src

format:
	ruff check --fix shared/src agents/*/src agents/*/tests
	ruff format shared/src agents/*/src agents/*/tests

# ===================== Docker =====================
docker-build:
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t agent-redator:latest ./agents/redator
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t agent-triador:latest ./agents/triador
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t agent-especialista:latest ./agents/especialista
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t agent-handoff:latest ./agents/handoff

docker-build-%:
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t agent-$*:latest ./agents/$*

docker-push:
	docker push $(REGISTRY)/agent-redator:$(TAG)
	docker push $(REGISTRY)/agent-triador:$(TAG)
	docker push $(REGISTRY)/agent-especialista:$(TAG)
	docker push $(REGISTRY)/agent-handoff:$(TAG)

# ===================== Kubernetes =====================
deploy-dev:
	kubectl apply -k k8s/overlays/dev

deploy-prod:
	kubectl apply -k k8s/overlays/prod

deploy-%:
	kubectl apply -k k8s/overlays/$*

diff-dev:
	kubectl diff -k k8s/overlays/dev

diff-prod:
	kubectl diff -k k8s/overlays/prod

undeploy-dev:
	kubectl delete -k k8s/overlays/dev --ignore-not-found=true

undeploy-prod:
	kubectl delete -k k8s/overlays/prod --ignore-not-found=true

# ===================== Local Development =====================
run-redator:
	PYTHONPATH=/home/cflb/agent-architecture/agents/redator/src python -m redator $(ARGS)

run-triador:
	PYTHONPATH=/home/cflb/agent-architecture/agents/triador/src python -m triador $(ARGS)

run-especialista:
	PYTHONPATH=/home/cflb/agent-architecture/agents/especialista/src python -m especialista $(ARGS)

run-handoff:
	PYTHONPATH=/home/cflb/agent-architecture/agents/handoff/src python -m handoff $(ARGS)

# Pipeline local completo
run-pipeline:
	@echo "=== Pipeline Local ==="
	@echo "1. Criando bruto.txt de teste..."
	@echo "ERROR - senha=secreto123 token=abc123\nDAG example_dag task task1 failed\nScheduler heartbeat missed" > /tmp/bruto.txt
	@echo "2. Redator..."
	PYTHONPATH=/home/cflb/agent-architecture/agents/redator/src python -m redator /tmp/bruto.txt /tmp/limpo.txt
	@echo "3. Triador..."
	PYTHONPATH=/home/cflb/agent-architecture/agents/triador/src python -m triador /tmp/limpo.txt
	@echo "4. Especialista (se ambíguo)..."
	@if grep -q "ambíguo.*true" /tmp/limpo.classificacao.json; then \
		PYTHONPATH=/home/cflb/agent-architecture/agents/especialista/src python -m especialista /tmp/limpo.classificacao.json; \
	else \
		echo "Classificação clara, pulando especialista"; \
	fi
	@echo "5. Handoff..."
	PYTHONPATH=/home/cflb/agent-architecture/agents/handoff/src python -m handoff /tmp/limpo.classificacao.json --canais slack
	@echo "=== Pipeline Concluído ==="

# ===================== Utilities =====================
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	find . -name ".coverage" -delete
	rm -rf htmlcov .coverage coverage.xml

adr:
	@ls -la docs/adr/

# ===================== CI Simulation =====================
ci: lint typecheck test
	@echo "CI passed locally!"

# ===================== Version =====================
version:
	@grep '^version' shared/pyproject.toml agents/*/pyproject.toml