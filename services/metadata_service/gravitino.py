from __future__ import annotations

import httpx


class GravitinoError(RuntimeError):
    """Gravitino REST 非 2xx 响应(携带 status + body)。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _is_conflict(e: GravitinoError) -> bool:
    # 按 HTTP 状态码判定(409),不靠字符串匹配——避免把 404"does not exist"误判为冲突。
    return e.status == 409


class GravitinoClient:
    """Gravitino REST 薄客户端(ADR-016 映射 + Task 1 实测端点/包络,见 spikes/gravitino_probe/RESULTS.md)。

    实测要点:
    - list catalogs/schemas/filesets 包络键 = ``identifiers``,名字取每项 ``name``。
    - get/create fileset 包络键 = ``fileset``;create 返回 HTTP 200(非 201)。
    - FILESET catalog 在 create schema 时对 schema 推导位置做真实 S3 getFileStatus 校验,
      故 ensure_catalog 必须强制 path-style(MinIO 单端点不应答 virtual-host)且 bucket 须先存在。

    transport 仅测试注入(httpx.MockTransport)。
    """

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(base_url=base_url, timeout=15, transport=transport)

    def close(self):
        self._c.close()

    def _get(self, p):
        r = self._c.get(p)
        if r.status_code >= 300:
            raise GravitinoError(f"{r.status_code} {r.text}", status=r.status_code)
        return r.json()

    def _post(self, p, body):
        r = self._c.post(p, json=body)
        if r.status_code >= 300:
            raise GravitinoError(f"{r.status_code} {r.text}", status=r.status_code)
        return r.json()

    @staticmethod
    def _names(resp) -> list[str]:
        return [i["name"] for i in resp.get("identifiers", [])]

    # ---- 导航 / 读 ----
    def list_catalogs(self, ml):
        return self._names(self._get(f"/api/metalakes/{ml}/catalogs"))

    def list_schemas(self, ml, cat):
        return self._names(self._get(f"/api/metalakes/{ml}/catalogs/{cat}/schemas"))

    def _fbase(self, ml, cat, sch):
        return f"/api/metalakes/{ml}/catalogs/{cat}/schemas/{sch}/filesets"

    def list_filesets(self, ml, cat, sch):
        return self._names(self._get(self._fbase(ml, cat, sch)))

    def get_fileset(self, ml, cat, sch, name):
        return self._get(f"{self._fbase(ml, cat, sch)}/{name}")["fileset"]

    # ---- 写 ----
    def create_fileset(self, ml, cat, sch, name, location, comment="", properties=None):
        return self._post(self._fbase(ml, cat, sch), {
            "name": name, "type": "EXTERNAL", "comment": comment,
            "storageLocation": location, "properties": properties or {}})["fileset"]

    # ---- ensure(幂等,容忍已存在;集成测试 / 自动注册用)----
    def ensure_metalake(self, ml):
        try:
            self._post("/api/metalakes", {"name": ml, "comment": ml})
        except GravitinoError as e:
            if not _is_conflict(e):
                raise

    def ensure_catalog(self, ml, cat, *, bucket, s3_endpoint, access_key, secret_key):
        """FILESET catalog → S3/MinIO。path-style 必须(Task 1 实测,见 RESULTS.md)。"""
        props = {
            "location": f"s3a://{bucket}/",
            "filesystem-providers": "s3",
            "s3-endpoint": s3_endpoint,
            "s3-access-key-id": access_key,
            "s3-secret-access-key": secret_key,
            "s3-path-style-access": "true",
            "gravitino.bypass.fs.s3a.path.style.access": "true",
        }
        try:
            self._post(f"/api/metalakes/{ml}/catalogs",
                       {"name": cat, "type": "FILESET", "comment": cat, "properties": props})
        except GravitinoError as e:
            if not _is_conflict(e):
                raise

    def ensure_schema(self, ml, cat, sch):
        try:
            self._post(f"/api/metalakes/{ml}/catalogs/{cat}/schemas", {"name": sch, "comment": sch})
        except GravitinoError as e:
            if not _is_conflict(e):
                raise
