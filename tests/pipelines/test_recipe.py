# tests/pipelines/test_recipe.py
import yaml
from pipelines.data_prep.recipe import build_recipe

def test_recipe_defaults_from_spike():
    r = yaml.safe_load(build_recipe(input_jsonl="/d/in.jsonl", out_dir="/d/out", np=3))
    assert r["executor_type"] == "ray" and r["ray_address"] == "auto"
    assert r["np"] == 3
    assert r["dataset_path"] == "/d/in.jsonl"
    assert r["export_path"] == "/d/out/cleaned.jsonl"
    ops = [list(o)[0] for o in r["process"]]
    assert ops == ["text_length_filter", "image_shape_filter", "image_aspect_ratio_filter"]

def test_recipe_custom_ops_override():
    r = yaml.safe_load(build_recipe("/i", "/o", np=2, process=[{"text_length_filter": {"min_len": 1}}]))
    assert r["process"] == [{"text_length_filter": {"min_len": 1}}]
