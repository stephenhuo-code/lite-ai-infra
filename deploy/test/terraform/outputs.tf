# deploy/test/terraform/outputs.tf
output "oss_endpoint" {
  description = "OSS S3 兼容 endpoint(填到 gateway 的 OSS_ENDPOINT)"
  value       = "https://oss-${var.region}.aliyuncs.com"
}

output "audit_bucket" {
  value = alicloud_oss_bucket.audit.bucket
}

output "gateway_access_key_id" {
  description = "gateway 审计写入用 AK id(OSS_ACCESS_KEY)"
  value       = alicloud_ram_access_key.gateway.id
}

output "gateway_access_key_secret" {
  description = "gateway 审计写入用 AK secret(OSS_SECRET_KEY)。敏感:`terraform output -raw gateway_access_key_secret`"
  value       = alicloud_ram_access_key.gateway.secret
  sensitive   = true
}

output "sts_role_arn" {
  description = "Spike C AssumeRole 的角色 ARN"
  value       = alicloud_ram_role.sts.arn
}
