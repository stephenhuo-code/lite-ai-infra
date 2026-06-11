# tests/pipelines/test_ingest.py
import io, json, tarfile
from pipelines.data_prep.ingest import wds_to_jsonl

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c4944415408d763f8cfc0000003010100c9fe92ef0000000049454e44ae426082")

def _mk_tar(p):
    with tarfile.open(p, "w") as tf:
        for key, txt in [("00001", "a cat"), ("00002", "blue sky")]:
            ti = tarfile.TarInfo(f"{key}.jpg"); ti.size = len(_PNG); tf.addfile(ti, io.BytesIO(_PNG))
            t = txt.encode(); ti2 = tarfile.TarInfo(f"{key}.txt"); ti2.size = len(t); tf.addfile(ti2, io.BytesIO(t))
        ti = tarfile.TarInfo("orphan.jpg"); ti.size = len(_PNG); tf.addfile(ti, io.BytesIO(_PNG))

def test_wds_to_jsonl_pairs_and_drops_orphans(tmp_path):
    tar_dir = tmp_path / "tars"; tar_dir.mkdir(); _mk_tar(tar_dir / "s-000.tar")
    out = tmp_path / "out"
    n = wds_to_jsonl(str(tar_dir), str(out))
    assert n == 2
    rows = [json.loads(l) for l in open(out / "data.jsonl")]
    assert rows[0]["text"] == "a cat"
    assert rows[0]["images"][0].startswith("/")
