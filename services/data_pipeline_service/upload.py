from __future__ import annotations
import uuid
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from libs.identity.ids import EnterpriseId
from pipelines.data_prep.paths import DatasetPaths
from services.data_pipeline_service.raw_store import RawSpec, RawDatasetStore


class ObjectMissing(Exception):
    """complete 时 OSS 上对象不存在 / 分片合并失败 → handler 映射 409。"""


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


class Uploader:
    """上传机制封装(ADR-020):key 服务端构造写死、presign 单/分片、complete 校验、GC。
    基础设施无感(持 raw_store + s3 + bucket),仿 runner 注入 build_app。授权(can())留在 handler。"""

    def __init__(self, raw_store: RawDatasetStore, s3, data_bucket: str, url_ttl: int = 900):
        self.raw_store = raw_store
        self.s3 = s3
        self.bucket = data_bucket
        self.url_ttl = url_ttl

    # ---- 请求上传:建记录 + presign ----
    def create_grant(self, *, name: str, enterprise_id: str, user_id: str, sub: str,
                     filename: str, multipart: bool, parts: int | None) -> dict:
        # owner 模型(ADR-024):key 三段服务端构造(C-1):eid/user 来自调用者(handler 取自 ctx),dataset/filename 经校验。
        paths = DatasetPaths(bucket=self.bucket, enterprise_id=EnterpriseId(enterprise_id),
                             user_id=user_id, dataset=name)   # DatasetPaths 校验 dataset
        oss_key = paths.raw_object_key(filename)                         # 校验 filename(失败抛 ValueError,零副作用)
        raw_id = "raw-" + uuid.uuid4().hex[:16]
        if multipart:
            n = parts or 1
            up = self.s3.create_multipart_upload(Bucket=self.bucket, Key=oss_key)
            upload_id = up["UploadId"]
            part_urls = [self.s3.generate_presigned_url(
                "upload_part",
                Params={"Bucket": self.bucket, "Key": oss_key, "UploadId": upload_id, "PartNumber": i},
                ExpiresIn=self.url_ttl) for i in range(1, n + 1)]
            url = None
        else:
            upload_id = None; part_urls = None
            url = self.s3.generate_presigned_url(
                "put_object", Params={"Bucket": self.bucket, "Key": oss_key}, ExpiresIn=self.url_ttl)
        self.raw_store.create(RawSpec(raw_id=raw_id, name=name, owner_user=sub,
                                      enterprise_id=enterprise_id, sub=sub, oss_key=oss_key, upload_id=upload_id))
        return {"raw_id": raw_id, "oss_key": oss_key, "url": url,
                "upload_id": upload_id, "part_urls": part_urls, "expires_in": self.url_ttl}

    def get_record(self, raw_id: str) -> dict | None:
        return self.raw_store.read(raw_id)

    # ---- 完成:校验对象 → ready/failed(key 从记录取,不信请求体;C-2)----
    def finalize(self, raw_id: str, parts: list[dict] | None) -> dict:
        spec = self.raw_store.load_spec(raw_id)
        if spec is None:
            raise ObjectMissing("record not found")
        key = spec.oss_key
        try:
            if spec.upload_id:
                mp = {"Parts": [{"ETag": p["etag"], "PartNumber": p["part_number"]}
                                for p in sorted(parts or [], key=lambda p: p["part_number"])]}
                self.s3.complete_multipart_upload(Bucket=self.bucket, Key=key,
                                                  UploadId=spec.upload_id, MultipartUpload=mp)
            head = self.s3.head_object(Bucket=self.bucket, Key=key)   # 仅证存在 + 取 size
        except (ClientError, KeyError) as e:
            self.raw_store.update(raw_id, "failed", error=str(e))
            raise ObjectMissing(str(e))
        self.raw_store.update(raw_id, "ready", size=head.get("ContentLength"))
        return self.raw_store.read(raw_id)

    def list_raw(self) -> list[dict]:
        return self.raw_store.list_raw()

    # ---- GC:对账 + 清超时 pending + abort 孤儿分片(ADR-020 §3 / I-2)----
    def gc(self, ttl_seconds: int) -> list[str]:
        """对超时 pending 先**对账**(ADR-020 I-2:核对 OSS 对象是否存在):
        单传记录若对象已落 OSS(complete 回调丢失的中间态)→ 补登 ready,不误删已上传数据;
        否则真孤儿 → multipart abort 计费分片 + 删记录。返回被回收(删除)的 id 列表。"""
        reaped: list[str] = []
        now = _now_epoch()
        for rec in self.raw_store.list_raw():
            if rec["status"] != "pending":
                continue
            created = rec.get("created_at")
            try:
                age = now - datetime.fromisoformat(created).timestamp() if created else ttl_seconds + 1
            except ValueError:
                age = ttl_seconds + 1
            if age < ttl_seconds:
                continue
            spec = self.raw_store.load_spec(rec["id"])
            if spec and not spec.upload_id:             # 单传:对账——对象=key 本身,存在即"授权了且已落"
                try:
                    head = self.s3.head_object(Bucket=self.bucket, Key=spec.oss_key)
                    self.raw_store.update(rec["id"], "ready", size=head.get("ContentLength"))
                    continue                            # 补登 ready,不删(挽回丢失 complete 的字节)
                except ClientError:
                    pass                                # 对象不存在 → 真孤儿,落到下方删除
            if spec and spec.upload_id:                 # 孤儿 multipart → abort(防 OSS 计费分片漏钱)
                try:
                    self.s3.abort_multipart_upload(Bucket=self.bucket, Key=spec.oss_key, UploadId=spec.upload_id)
                except ClientError:
                    pass
            self.raw_store.delete(rec["id"])
            reaped.append(rec["id"])
        return reaped
