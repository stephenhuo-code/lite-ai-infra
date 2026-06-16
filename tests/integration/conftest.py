import stat, sys, textwrap
import pytest


@pytest.fixture
def dj_passthrough_bin(tmp_path):
    """DJ 桩:解析 --config recipe.yaml 取 dataset_path/export_path,把输入 jsonl 原样
    拷到 export_path(模拟 DJ 清洗为恒等)。复用既有 minio_s3/minio_bucket fixture。"""
    script = tmp_path / "dj_passthrough.py"
    # 注:DJ(Ray executor)把 export_path 当作**目录**写分片 part 文件;
    # lance_writer 据此 glob `{export_path}/*.json*`。桩据此在 export_path 目录内放一个分片。
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import sys, shutil, pathlib, yaml
        cfg = yaml.safe_load(open(sys.argv[sys.argv.index("--config") + 1]))
        out = pathlib.Path(cfg["export_path"]); out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cfg["dataset_path"], out / "cleaned.jsonl")
    """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return str(script)
