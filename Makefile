.PHONY: test test-integration lint contract-check dev-up dev-down sync gen up down ps api-docs api-docs-down
sync:             ; uv sync --extra dev
gen:              ; uv run datamodel-codegen --disable-timestamp --input contracts/openapi/identity-org.yaml --input-file-type openapi --output libs/contracts_gen/identity_org_models.py
test:             ; uv run pytest -q
test-integration: ; uv run pytest -q -m integration
lint:             ; uv run lint-imports && bash scripts/ci_guards.sh
contract-check:   ; oasdiff breaking contracts/openapi/identity-org.yaml@HEAD~1 contracts/openapi/identity-org.yaml || true
dev-up:           ; docker compose -f deploy/dev/docker-compose.yml up -d
dev-down:         ; docker compose -f deploy/dev/docker-compose.yml down -v
data-prep:        ; uv run python -m pipelines.data_prep $(ARGS)
JWKS ?= http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs
# 一键起停全部(deps 容器 + 全部服务进程)
up:               ; docker compose -f deploy/dev/docker-compose.yml up -d && JWKS=$(JWKS) bash scripts/dev_services.sh up
down:             ; bash scripts/dev_services.sh down; docker compose -f deploy/dev/docker-compose.yml down
ps:               ; bash scripts/dev_services.sh ps
# 聚合 Swagger:自动发现 contracts/openapi/*.yaml(一个页面下拉看全部 API)
api-docs:         ; URLS=$$(uv run python scripts/swagger_urls.py) docker compose -f deploy/dev/swagger-ui.yml up -d && echo "Swagger UI(全部契约): http://localhost:8088"
api-docs-down:    ; docker compose -f deploy/dev/swagger-ui.yml down
# 单服务前台(开发热重载用)
run-identity:     ; LITEAI_JWKS_URL=$(JWKS) uv run uvicorn services.identity_org_service.main:app --port 8001 --reload
run-gateway:      ; IDENTITY_ORG_URL=http://localhost:8001 uv run uvicorn services.gateway.main:app --port 8090 --reload
