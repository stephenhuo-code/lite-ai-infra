.PHONY: test test-integration lint contract-check dev-up dev-down sync gen up down ps api-docs api-docs-down dj-setup fe-install fe-types fe-build fe-lint fe-test fe-e2e
sync:             ; uv sync --extra dev
# dev/prod parity:建独立 .dj-venv(同云上 Data-Juicer+Ray);本地真跑数据管线前先 `make dj-setup` 一次
dj-setup:         ; bash scripts/dj_setup.sh
gen:              ; uv run datamodel-codegen --disable-timestamp --input contracts/openapi/identity-org.yaml --input-file-type openapi --output libs/contracts_gen/identity_org_models.py && uv run datamodel-codegen --disable-timestamp --input contracts/openapi/metadata.yaml --input-file-type openapi --output libs/contracts_gen/metadata_models.py && uv run datamodel-codegen --disable-timestamp --input contracts/openapi/data-pipeline.yaml --input-file-type openapi --output libs/contracts_gen/data_pipeline_models.py
test:             ; uv run pytest -q
test-integration: ; uv run pytest -q -m integration
lint:             ; uv run lint-imports && bash scripts/ci_guards.sh
contract-check:   ; oasdiff breaking contracts/openapi/identity-org.yaml@HEAD~1 contracts/openapi/identity-org.yaml || true
dev-up:           ; docker compose -f deploy/dev/docker-compose.yml up -d
dev-down:         ; docker compose -f deploy/dev/docker-compose.yml down -v
data-prep:        ; uv run python -m pipelines.data_prep $(ARGS)
JWKS ?= http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs
# 一键起停全部(deps 容器 + 全部服务进程)
up:               ; docker compose -f deploy/dev/docker-compose.yml up -d && docker compose -f deploy/dev/gravitino.yml up -d && JWKS=$(JWKS) bash scripts/dev_services.sh up
down:             ; bash scripts/dev_services.sh down; docker compose -f deploy/dev/gravitino.yml down; docker compose -f deploy/dev/docker-compose.yml down
ps:               ; bash scripts/dev_services.sh ps
# 聚合 Swagger:自动发现 contracts/openapi/*.yaml(一个页面下拉看全部 API)
api-docs:         ; URLS=$$(uv run python scripts/swagger_urls.py) docker compose -f deploy/dev/swagger-ui.yml up -d && echo "Swagger UI(全部契约): http://localhost:8088"
api-docs-down:    ; docker compose -f deploy/dev/swagger-ui.yml down
# 单服务前台(开发热重载用)
run-identity:     ; LITEAI_JWKS_URL=$(JWKS) uv run uvicorn services.identity_org_service.main:app --port 8001 --reload
run-metadata:     ; LITEAI_JWKS_URL=$(JWKS) GRAVITINO_URL=http://localhost:8091 uv run uvicorn services.metadata_service.main:app --port 8002 --reload
run-gateway:      ; IDENTITY_ORG_URL=http://localhost:8001 METADATA_URL=http://localhost:8002 DATA_PIPELINE_URL=http://localhost:8003 LITEAI_JWKS_URL=$(JWKS) BFF_SESSION_KEY=5SetoEInIYji6K_tuQEB8pJ8NCaoC5yi2vNAxtPi7gg= OIDC_CLIENT_ID=lite-ai-web OIDC_CLIENT_SECRET=dev-web-secret OIDC_ISSUER=http://localhost:8080/realms/lite-ai BFF_REDIRECT_URI=http://localhost:8090/auth/callback uv run uvicorn services.gateway.main:app --port 8090 --reload
run-data-pipeline: ; LITEAI_JWKS_URL=$(JWKS) JOBS_DIR=./.dev/jobs OSS_ENDPOINT=http://localhost:9000 OSS_ACCESS_KEY=minio OSS_SECRET_KEY=minio123 OSS_REGION=us-east-1 DATA_BUCKET=lite-ai AUDIT_BUCKET=lite-ai DJ_BIN=$(PWD)/.dj-venv/bin/dj-process uv run uvicorn services.data_pipeline_service.main:app --port 8003 --reload
# 数据域控制台前端(Plan 8b):node 工具链隔离在 frontend/
fe-install: ; cd frontend && npm install
fe-types:   ; cd frontend && npx openapi-typescript ../contracts/openapi/metadata.yaml -o src/api/types-metadata.ts && npx openapi-typescript ../contracts/openapi/data-pipeline.yaml -o src/api/types-datapipeline.ts && npx openapi-typescript ../contracts/openapi/identity-org.yaml -o src/api/types-identity.ts
fe-build:   ; cd frontend && npm run build
fe-lint:    ; cd frontend && npm run lint
fe-test:    ; cd frontend && npx vitest run
fe-e2e:     ; cd frontend && npx playwright test
