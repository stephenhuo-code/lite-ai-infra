.PHONY: test test-integration lint contract-check deps-base deps-dev dev-up dev-down dev-reset sync gen up down ps api-docs api-docs-down dj-setup fe-install fe-types fe-build fe-lint fe-test fe-e2e bootstrap-catalog omnigent-up omnigent-down ws-up ws-down provision-orgs
EID ?= ent-demo
sync:             ; uv sync --extra dev
# dev/prod parity:建独立 .dj-venv(同云上 Data-Juicer+Ray);本地真跑数据管线前先 `make dj-setup` 一次
dj-setup:         ; bash scripts/dj_setup.sh
gen:              ; uv run datamodel-codegen --disable-timestamp --input contracts/openapi/identity-org.yaml --input-file-type openapi --output libs/contracts_gen/identity_org_models.py && uv run datamodel-codegen --disable-timestamp --input contracts/openapi/metadata.yaml --input-file-type openapi --output libs/contracts_gen/metadata_models.py && uv run datamodel-codegen --disable-timestamp --input contracts/openapi/data-pipeline.yaml --input-file-type openapi --output libs/contracts_gen/data_pipeline_models.py
test:             ; uv run pytest -q
test-integration: ; uv run pytest -q -m integration
lint:             ; uv run lint-imports && bash scripts/ci_guards.sh
contract-check:   ; oasdiff breaking contracts/openapi/identity-org.yaml@HEAD~1 contracts/openapi/identity-org.yaml || true
# 基础依赖(MinIO + Keycloak + Postgres)—— CI 过渡期也只需这些
deps-base:        ; docker compose -f deploy/dev/docker-compose.yml up -d
# 完整本地(基础 + dev-only:Gravitino)—— 叠加,不可单起 overlay(gravitino 的 external 网络由基础档创建)
deps-dev:         ; docker compose -f deploy/dev/docker-compose.yml up -d && docker compose -f deploy/dev/gravitino.yml up -d
dev-up:           ; $(MAKE) deps-dev          # 兼容旧名
# 保数据停(默认):不删卷,dev 数据(MinIO/PG/Gravitino)重启后保留
dev-down:         ; docker compose -f deploy/dev/gravitino.yml down; docker compose -f deploy/dev/docker-compose.yml down
# 清空停(显式毁灭性):删三类命名卷;改 PG 密码 / 要干净重来时用
dev-reset:        ; docker compose -f deploy/dev/gravitino.yml down -v; docker compose -f deploy/dev/docker-compose.yml down -v
data-prep:        ; uv run python -m pipelines.data_prep $(ARGS)
# omnigent server(Plan 9a):自编译 server+host:dev 镜像 → 起 header-trust 多用户 compose
omnigent-up:      ; bash scripts/omnigent_build.sh dev && docker compose -f deploy/dev/omnigent/docker-compose.yml up -d
omnigent-down:    ; docker compose -f deploy/dev/omnigent/docker-compose.yml down
# KC 组织置备(realm 导入后把 alice/bob 加入企业 org + organization scope);幂等,可重复跑
provision-orgs:   ; uv run python scripts/provision_orgs.py
# Plan 9a Workspace 一键编排:deps-dev → provision-orgs → omnigent-up → services up,逐步等就绪(见 scripts/ws_up.sh)
# 前端不后台化:脚本末尾打印 `cd frontend && npm run dev`(vite:5173,代理 /auth /v1 → gateway:8090)
ws-up:            ; bash scripts/ws_up.sh
# 反向停:services → omnigent → deps;再清理动态拉起、不在 compose 里的 managed host 容器(见 scripts/ws_down.sh)
ws-down:          ; bash scripts/ws_down.sh
ENV ?= local
export LITEAI_ENV = $(ENV)
LOAD = uv run python scripts/load_env.py
# 一键起停全部(deps 容器 + 全部服务进程)
up:               ; $(MAKE) deps-dev && bash scripts/dev_services.sh up
down:             ; bash scripts/dev_services.sh down; $(MAKE) dev-down
ps:               ; bash scripts/dev_services.sh ps
# 聚合 Swagger:自动发现 contracts/openapi/*.yaml(一个页面下拉看全部 API)
api-docs:         ; URLS=$$(uv run python scripts/swagger_urls.py) docker compose -f deploy/dev/swagger-ui.yml up -d && echo "Swagger UI(全部契约): http://localhost:8088"
api-docs-down:    ; docker compose -f deploy/dev/swagger-ui.yml down
# 单服务前台(开发热重载用)
run-identity:      ; env $$($(LOAD) identity) uv run uvicorn services.identity_org_service.main:app --port 8001 --reload
run-metadata:      ; env $$($(LOAD) metadata) uv run uvicorn services.metadata_service.main:app --port 8002 --reload
run-gateway:       ; env $$($(LOAD) gateway) uv run uvicorn services.gateway.main:app --port 8090 --reload
run-data-pipeline: ; env $$($(LOAD) data-pipeline) uv run uvicorn services.data_pipeline_service.main:app --port 8003 --reload
# 一次性建企业目录骨架(metalake+catalog+schema);需 metadata env 带 OSS_*/DATA_BUCKET
bootstrap-catalog: ; env $$($(LOAD) metadata) uv run python scripts/bootstrap_catalog.py $(EID)
# 数据域控制台前端(Plan 8b):node 工具链隔离在 frontend/
fe-install: ; cd frontend && npm install
fe-types:   ; cd frontend && npx openapi-typescript ../contracts/openapi/metadata.yaml -o src/api/types-metadata.ts && npx openapi-typescript ../contracts/openapi/data-pipeline.yaml -o src/api/types-datapipeline.ts && npx openapi-typescript ../contracts/openapi/identity-org.yaml -o src/api/types-identity.ts
fe-build:   ; cd frontend && npm run build
fe-lint:    ; cd frontend && npm run lint
fe-test:    ; cd frontend && npx vitest run
fe-e2e:     ; cd frontend && npx playwright test
