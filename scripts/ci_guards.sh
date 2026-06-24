#!/usr/bin/env bash
set -euo pipefail
fail=0
# 守卫 1：display_name 不得出现在资源命名代码（libs/services 的 .py）。
# 例外:界面渲染/展示用途(§1.4 允许显示名作展示,FR-002b)须显式标注 `display-name-ok`,
# 标注行经评审豁免;未标注的 display_name(资源名/路径/schema/label)一律 FAIL。
# contracts_gen 是契约自动生成的 DTO(display_name 是契约展示字段,非手写资源命名)→ 排除。
if grep -rnE 'display_name' libs services --include='*.py' --exclude-dir=contracts_gen | grep -viE 'test|comment|display-name-ok'; then
  echo "GUARD FAIL: display_name referenced in code (presentation use 须标注 display-name-ok)"; fail=1; fi
# 守卫 2：authz 引擎之外不得散落 'if ... enterprise_id ==' (必须经 can())
if grep -rnE 'if .*enterprise_id *==' libs services --include='*.py' | grep -v 'libs/authz/engine.py'; then
  echo "GUARD FAIL: scattered enterprise_id comparison (use can())"; fail=1; fi
exit $fail
