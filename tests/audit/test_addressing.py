# tests/audit/test_addressing.py
# Spike C 实测固化:真 OSS 拒 path-style + 拒 boto3>=1.36 流式 checksum。
# (原寄居 tests/gateway/test_gateway.py;Plan 3 T6 gateway 改反代壳后迁回此处——本就测 libs/audit。)
from libs.audit.oss_audit import addressing_style, oss_boto3_config


def test_addressing_style_adapts_to_endpoint():
    assert addressing_style("https://oss-cn-hangzhou.aliyuncs.com") == "virtual"
    assert addressing_style("https://oss-cn-hangzhou-internal.aliyuncs.com") == "virtual"
    assert addressing_style("http://localhost:9000") == "path"


def test_addressing_style_explicit_override():
    assert addressing_style("https://oss-cn-hangzhou.aliyuncs.com", explicit="path") == "path"


def test_oss_boto3_config_checksum_when_required():
    cfg = oss_boto3_config("https://oss-cn-hangzhou.aliyuncs.com")
    assert cfg.request_checksum_calculation == "when_required"
    assert cfg.s3["addressing_style"] == "virtual"
