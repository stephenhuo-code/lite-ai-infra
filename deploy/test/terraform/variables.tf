# deploy/test/terraform/variables.tf
variable "region" {
  description = "阿里云 region,如 cn-hangzhou / cn-shanghai"
  type        = string
  default     = "cn-hangzhou"
}

variable "audit_bucket" {
  description = "审计 OSS bucket 名(全局唯一,自行加前缀避免冲突,如 lite-ai-audit-<你的标识>)"
  type        = string
}

variable "gateway_user_name" {
  description = "gateway 审计写入用的 RAM 用户名(最小权限:仅本 bucket 的 audit/ 前缀)"
  type        = string
  default     = "lite-ai-gateway-audit"
}

variable "sts_role_name" {
  description = "Spike C 用的可被 AssumeRole 的 RAM 角色名(STS 受限凭据演示)"
  type        = string
  default     = "lite-ai-audit-sts"
}
