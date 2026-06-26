from services.dev_workspace_mcp.tools.pipeline import dj_run_command, scaffold_dj_recipe


def test_scaffold_has_dataset_and_export():
    y = scaffold_dj_recipe(dataset="coco", export="output/coco-clean.lance",
                           ops=[{"text_length_filter": {"min_len": 3}}])
    assert "coco" in y and "output/coco-clean.lance" in y and "text_length_filter" in y


def test_run_command_uses_recipe_path():
    cmd = dj_run_command(recipe_path="recipe.py")
    assert "recipe.py" in cmd and "dj-process" in cmd
