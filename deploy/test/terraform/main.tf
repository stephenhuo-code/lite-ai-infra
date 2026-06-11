# deploy/test/terraform/main.tf
# 测试环境的 OSS + RAM 最小权限。满足:审计追加写(distinct key,非真 append)、
# 路径前缀隔离(audit/*)、STS 受限凭据(Spike C)。对应 spec E2/E3、ADR-010/013。
#
# 凭据:不写进 .tf。用环境变量 ALICLOUD_ACCESS_KEY / ALICLOUD_SECRET_KEY(或 aliyun CLI profile)。
# 警告:本配置会创建 RAM AccessKey,其 secret 会落进 tfstate —— tfstate 含密,务必妥善保管
#       (勿入库;生产建议用加密远端 backend)。

terraform {
  required_version = ">= 1.5"
  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = "~> 1.230"
    }
  }
}

provider "alicloud" {
  region = var.region
}

# --- OSS 审计 bucket（私有） ---
resource "alicloud_oss_bucket" "audit" {
  bucket = var.audit_bucket
}

resource "alicloud_oss_bucket_acl" "audit" {
  bucket = alicloud_oss_bucket.audit.bucket
  acl    = "private"
}

# --- 最小权限策略：仅本 bucket 的 audit/ 前缀，可列/读/写 ---
locals {
  audit_policy = jsonencode({
    Version = "1"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["oss:ListObjects", "oss:GetBucketInfo"]
        Resource = ["acs:oss:*:*:${var.audit_bucket}"]
      },
      {
        Effect   = "Allow"
        Action   = ["oss:PutObject", "oss:GetObject"]
        Resource = ["acs:oss:*:*:${var.audit_bucket}/audit/*"]
      }
    ]
  })
}

resource "alicloud_ram_policy" "audit" {
  policy_name     = "lite-ai-audit-write"
  policy_document = local.audit_policy
  description     = "least-priv: write/read only under <bucket>/audit/*"
  force           = true
}

# --- gateway 审计写入用的 RAM 用户 + AccessKey（对应 main.py 的静态 AK/SK） ---
resource "alicloud_ram_user" "gateway" {
  name = var.gateway_user_name
}

resource "alicloud_ram_user_policy_attachment" "gateway" {
  policy_name = alicloud_ram_policy.audit.policy_name
  policy_type = "Custom"
  user_name   = alicloud_ram_user.gateway.name
}

resource "alicloud_ram_access_key" "gateway" {
  user_name = alicloud_ram_user.gateway.name
}

# --- Spike C：可被该用户 AssumeRole 的受限角色（STS 受限凭据） ---
resource "alicloud_ram_role" "sts" {
  # 信任策略引用 gateway 用户的 ARN(字符串拼接,terraform 无法推断依赖)——
  # 必须显式等用户建成,否则 CreateRole 报 "user not exists"
  depends_on = [alicloud_ram_user.gateway]
  role_name  = var.sts_role_name
  assume_role_policy_document = jsonencode({
    Version = "1"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          # 允许本账号下的 RAM 用户(gateway)扮演此角色。${} 内为账号侧拼接。
          RAM = ["acs:ram::${data.alicloud_account.current.id}:user/${var.gateway_user_name}"]
        }
      }
    ]
  })
  description = "Spike C: STS 受限凭据演示(数据路径)"
  force       = true
}

resource "alicloud_ram_role_policy_attachment" "sts" {
  policy_name = alicloud_ram_policy.audit.policy_name
  policy_type = "Custom"
  role_name   = alicloud_ram_role.sts.role_name
}

data "alicloud_account" "current" {}
