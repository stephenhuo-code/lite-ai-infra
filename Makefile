.PHONY: test test-integration lint contract-check dev-up dev-down sync gen
sync:             ; uv sync --extra dev
gen:              ; uv run datamodel-codegen --disable-timestamp --input contracts/openapi/identity-org.yaml --input-file-type openapi --output libs/contracts_gen/identity_org_models.py
test:             ; uv run pytest -q
test-integration: ; uv run pytest -q -m integration
lint:             ; uv run lint-imports && bash scripts/ci_guards.sh
contract-check:   ; oasdiff breaking contracts/openapi/identity-org.yaml@HEAD~1 contracts/openapi/identity-org.yaml || true
dev-up:           ; docker compose -f deploy/dev/docker-compose.yml up -d
dev-down:         ; docker compose -f deploy/dev/docker-compose.yml down -v
data-prep:        ; uv run python -m pipelines.data_prep $(ARGS)
api-docs:         ; docker compose -f deploy/dev/swagger-ui.yml up -d && echo "Swagger UI: http://localhost:8088"
