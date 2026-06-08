.PHONY: test test-integration lint contract-check dev-up dev-down sync
sync:             ; uv sync --extra dev
test:             ; uv run pytest -q || [ $$? -eq 5 ]
test-integration: ; uv run pytest -q -m integration
lint:             ; uv run lint-imports && bash scripts/ci_guards.sh
contract-check:   ; oasdiff breaking contracts/openapi/identity-org.yaml@HEAD~1 contracts/openapi/identity-org.yaml || true
dev-up:           ; docker compose -f deploy/dev/docker-compose.yml up -d
dev-down:         ; docker compose -f deploy/dev/docker-compose.yml down -v
