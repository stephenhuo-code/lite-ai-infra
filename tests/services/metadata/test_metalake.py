# tests/services/metadata/test_metalake.py
# enterprise_id 改不透明 org alias(ADR-025):metalake = alias.replace("-","_"),
# 对不透明 alias(ent-demo)产出合法 Gravitino metalake 名([a-z0-9_])。
from services.metadata_service.app import _metalake


def test_metalake_maps_opaque_alias_to_legal_name():
    assert _metalake("ent-demo") == "ent_demo"   # 合法 metalake 名 [a-z0-9_]
    assert _metalake("e-0001") == "e_0001"        # 旧式 alias 仍兼容
    assert _metalake("ent-demo").replace("_", "").isalnum()
