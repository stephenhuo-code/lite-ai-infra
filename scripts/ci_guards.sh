#!/usr/bin/env bash
set -euo pipefail
fail=0
# 守卫 1：display_name 不得出现在资源命名代码（libs/services 的 .py）
if grep -rnE 'display_name' libs services --include='*.py' | grep -viE 'test|comment'; then
  echo "GUARD FAIL: display_name referenced in code"; fail=1; fi
# 守卫 2：authz 引擎之外不得散落 'if ... enterprise_id ==' (必须经 can())
if grep -rnE 'if .*enterprise_id *==' libs services --include='*.py' | grep -v 'libs/authz/engine.py'; then
  echo "GUARD FAIL: scattered enterprise_id comparison (use can())"; fail=1; fi
exit $fail
