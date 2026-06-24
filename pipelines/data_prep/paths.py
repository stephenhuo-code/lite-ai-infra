# pipelines/data_prep/paths.py
from __future__ import annotations
import re
from dataclasses import dataclass

from libs.identity.ids import EnterpriseId

_RE_DATASET = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_RE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")  # 单段文件名,首字符非 '.' → 排除 '..'/'.hidden';无 '/' → 无路径穿越

@dataclass(frozen=True)
class DatasetPaths:
    """资源命名只含不透明 ID(宪法 §1.4):oss://<bucket>/<eid>/<user>/{raw,cleaned,processed}/…
    owner 模型(ADR-024):路径按上传用户(user_id=ctx.user=sub,§1.4 不透明),不再按 group。"""
    bucket: str
    enterprise_id: EnterpriseId
    user_id: str
    dataset: str

    def __post_init__(self):
        if not _RE_DATASET.match(self.dataset):
            raise ValueError(f"invalid dataset name: {self.dataset!r}")

    @property
    def _base(self) -> str:
        return f"{self.enterprise_id}/{self.user_id}"

    @property
    def raw_prefix(self) -> str:
        return f"{self._base}/raw/{self.dataset}/"

    def raw_object_key(self, filename: str) -> str:
        """本组 raw/ 下的完整对象 key。文件名段服务端校验(ADR-020 C-1):
        无 '/' 杜绝路径穿越,首字符非 '.' 杜绝 '..'/隐藏文件。"""
        if not _RE_FILENAME.match(filename):
            raise ValueError(f"invalid filename: {filename!r}")
        return self.raw_prefix + filename

    @property
    def cleaned_prefix(self) -> str:
        return f"{self._base}/cleaned/{self.dataset}/"

    @property
    def processed_uri(self) -> str:
        return f"s3://{self.bucket}/{self._base}/processed/{self.dataset}.lance"
