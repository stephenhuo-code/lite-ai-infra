# pipelines/data_prep/paths.py
from __future__ import annotations
import re
from dataclasses import dataclass

from libs.identity.ids import EnterpriseId, GroupId

_RE_DATASET = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

@dataclass(frozen=True)
class DatasetPaths:
    """资源命名只含不透明 ID(宪法 §1.4):oss://<bucket>/<eid>/<gid>/{raw,cleaned,processed}/…"""
    bucket: str
    enterprise_id: EnterpriseId
    group_id: GroupId
    dataset: str

    def __post_init__(self):
        if not _RE_DATASET.match(self.dataset):
            raise ValueError(f"invalid dataset name: {self.dataset!r}")

    @property
    def _base(self) -> str:
        return f"{self.enterprise_id}/{self.group_id}"

    @property
    def raw_prefix(self) -> str:
        return f"{self._base}/raw/{self.dataset}/"

    @property
    def cleaned_prefix(self) -> str:
        return f"{self._base}/cleaned/{self.dataset}/"

    @property
    def processed_uri(self) -> str:
        return f"s3://{self.bucket}/{self._base}/processed/{self.dataset}.lance"
