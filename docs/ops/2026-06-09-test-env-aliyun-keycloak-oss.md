# 测试环境(阿里云)部署 runbook —— Keycloak + OSS(最小集)

> **范围(本轮):** 在阿里云立起 S0 出口① 数据 Spike 所需的**最小测试环境**:单台 ECS 跑 Keycloak 26.6.2(Postgres 持久化)+ 一个受最小权限约束的 OSS 审计 bucket。
> **不在本轮:** ACK 集群、数据栈(Ray/Volcano/Data-Juicer/Gravitino)、gateway 服务上云 —— 那些按 spec §8.8 留到 Sprint 1–2。
>
> **本计划归属(回答"哪个 Sprint"):** design spec §5.3 把"Keycloak 部署 + IaC 入库"排在 **Sprint 0(P3)**;§8.8 增量表却把"staging 集群初始化 + Helm"放到 **Sprint 2**、Sprint 0 仅"dev compose + staging 规划"。两处口径不一致。本 runbook 做的是 §5.3 的 Sprint 0 P3 那条(补做被 S0 代码计划推迟的环境前置),不含 §8.8 的全栈。
>
> **执行约定:** 凡涉及阿里云凭据的命令**由你在本地执行**(我无你的云凭据)。每步给了期望证据,照"证据先于断言"验收(宪法 §3.2)。

---

## 0. 前置

**工具(本地):**
```bash
brew install aliyun-cli terraform   # 或各自官方安装
aliyun configure                     # 配 RAM 子账号 AK/SK + 默认 region(如 cn-hangzhou)
terraform -version                   # >= 1.5
```

**阿里云账号:** 一个有权限创建 OSS / RAM / ECS / VPC 的 RAM 子账号(provisioning 用)。生产请遵最小权限;test 阶段可临时给较宽权限,完成后回收。

**region:** 全程用同一个 region(下文以 `cn-hangzhou` 为例)。OSS bucket 与 ECS 建议同 region,降延迟。

---

## 1. OSS + RAM(Terraform)—— 你执行

创建审计 bucket、最小权限策略、gateway 写入用 RAM 用户 + AK、Spike C 的 STS 角色。

```bash
cd deploy/test/terraform
export ALICLOUD_ACCESS_KEY=<provisioning 子账号 AK>
export ALICLOUD_SECRET_KEY=<provisioning 子账号 SK>

terraform init
terraform apply \
  -var 'region=cn-hangzhou' \
  -var 'audit_bucket=lite-ai-audit-<你的唯一后缀>'   # bucket 名全局唯一
```

**期望证据:** `Apply complete! Resources: N added`。取输出:
```bash
terraform output                                   # 看 oss_endpoint / audit_bucket / sts_role_arn / AK id
terraform output -raw gateway_access_key_secret    # 取 AK secret(敏感,勿贴聊天/勿入库)
```

> ⚠️ **tfstate 含 AK secret**,已被 `.gitignore` 忽略;务必妥善保管,勿提交。生产改用加密远端 backend。

---

## 2. ECS 实例 + 安全组 —— 你执行

从零起一台小 ECS(2C4G 足够跑 Keycloak+PG)。**网络(VPC/vSwitch)从零时,用控制台一键创建实例更快**;若已有 VPC,用 CLI:

```bash
# 安全组:只放行你自己出口 IP 的 22(SSH)和 8080(Keycloak),不要 0.0.0.0/0
MYIP=$(curl -s ifconfig.me)
aliyun ecs AuthorizeSecurityGroup --SecurityGroupId <sg-id> \
  --IpProtocol tcp --PortRange 22/22   --SourceCidrIp ${MYIP}/32
aliyun ecs AuthorizeSecurityGroup --SecurityGroupId <sg-id> \
  --IpProtocol tcp --PortRange 8080/8080 --SourceCidrIp ${MYIP}/32
```

**期望证据:** ECS 处于 `Running`,记下**公网 IP** `ECS_IP`;`ssh root@$ECS_IP` 能登。

---

## 3. 在 ECS 上起 Keycloak —— 你执行

```bash
# 3a. 装 docker(ECS 上;以 Alibaba Cloud Linux / Ubuntu 为例)
ssh root@$ECS_IP 'curl -fsSL https://get.docker.com | sh && systemctl enable --now docker'

# 3b. 把 deploy/ 子树拷上去(test compose 用相对路径挂 ../dev/keycloak 的同一份 realm)
rsync -av --exclude='.env' ../../deploy root@$ECS_IP:/opt/lite-ai/

# 3c. 在 ECS 上填 .env 并起服务
ssh root@$ECS_IP 'cd /opt/lite-ai/deploy/test && cp .env.example .env && \
  sed -i "s/change-me-strong/$(openssl rand -hex 12)/; s/change-me-strong-db/$(openssl rand -hex 12)/" .env && \
  docker compose up -d'
```

**期望证据:** `docker compose ps` 两个容器(postgres healthy、keycloak up)。
> 管理员密码已随机化写进 ECS 上的 `.env`;需要时 `ssh ... cat /opt/lite-ai/deploy/test/.env` 取。

---

## 4. 验证 Keycloak token 带 groups claim(= S0 出口②,真机)

```bash
curl -fsS http://$ECS_IP:8080/realms/lite-ai/.well-known/openid-configuration | head -c 120; echo
# 期望:含 "issuer":"http://$ECS_IP:8080/realms/lite-ai"(realm 导入成功)

TOKEN=$(curl -fsS -d client_id=gateway -d client_secret=dev-secret \
  -d username=alice -d password=alice -d grant_type=password \
  http://$ECS_IP:8080/realms/lite-ai/protocol/openid-connect/token | \
  python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
python3 -c "import jwt;print(jwt.decode('$TOKEN',options={'verify_signature':False})['groups'])"
# 期望:['/e-0001/g-0001/members']
```

---

## 5. 验证 OSS 审计写入(= S0 出口③ 等价,云上真 OSS)

用 terraform 输出的 gateway AK 指向真 OSS 跑 gateway(可在本地或 ECS):

```bash
export TF=deploy/test/terraform
LITEAI_ALLOW_TEST_CLAIMS=0 \
LITEAI_JWKS_URL=http://$ECS_IP:8080/realms/lite-ai/protocol/openid-connect/certs \
OSS_ENDPOINT=$(terraform -chdir=$TF output -raw oss_endpoint) \
OSS_ACCESS_KEY=$(terraform -chdir=$TF output -raw gateway_access_key_id) \
OSS_SECRET_KEY=$(terraform -chdir=$TF output -raw gateway_access_key_secret) \
OSS_REGION=cn-hangzhou \
AUDIT_BUCKET=$(terraform -chdir=$TF output -raw audit_bucket) \
  uv run uvicorn services.gateway.main:app --port 8000 &
sleep 4
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/jobs/job-1   # 期望 200(本企业)
aliyun oss ls oss://$(terraform -chdir=$TF output -raw audit_bucket)/audit/ --recursive   # 期望:有 .jsonl
```

> `main.py` 已对 OSS 强制 path-style 寻址(boto3 S3 兼容,spec E2:不用 OSS 专属 SDK)。
> 这一步同时坐实 **Spike C**(真 OSS 审计 + 路径前缀隔离);STS 受限凭据用 `sts_role_arn` 走 `aliyun sts AssumeRole` 再验一遍。

---

## 6. 安全 / 硬化(测试环境最低线)

- 安全组**只放行自己 IP**,绝不 `0.0.0.0/0`;Spike 跑完即关 8080 入站。
- `start-dev` 仅测试用。上 staging/prod 换 `start` + `KC_HOSTNAME` + TLS(ACM 证书 / 反代)。
- Keycloak 管理员密码已随机化;`dev-secret`(client secret)是 dev 占位,真机请在 realm 里轮换。
- RAM 用户/角色已最小权限(仅 `<bucket>/audit/*`);provisioning 用的宽权限子账号用完回收。

## 7. 映射回 S0 出口 / 验收

- 立起后即可跑 **数据 Spike 1(Lance on OSS 延迟)/ Spike 2(Data-Juicer+Ray)** —— 它们是 **S0 出口① 硬条件**(本环境提供真 OSS;Ray/Data-Juicer 仍需在 ECS/后续 ACK 上装,属下一步)。
- §4=出口②、§5=出口③ 的**真机复验**;Spike A(Keycloak Organizations claim 稳定性)亦可在此环境复验,结论回写 ADR-010/011。

## 8. 省钱 / 拆栈

```bash
ssh root@$ECS_IP 'cd /opt/lite-ai/deploy/test && docker compose down'   # 停服务(留数据卷)
aliyun ecs StopInstance --InstanceId <i-xxx>                            # 不用时停 ECS(省钱)
cd deploy/test/terraform && terraform destroy                          # 彻底拆 OSS+RAM(注意 bucket 需先清空)
```
