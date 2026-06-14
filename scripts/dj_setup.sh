#!/usr/bin/env bash
# dev/prod parity: build a standalone .dj-venv with the same Data-Juicer + Ray as cloud (/opt/dj-venv).
#
# Why a separate venv (not the main .venv) — see ADR-018 / Plan 5:
#   1) topology parity: cloud runs DJ in its own env (S1 /opt/dj-venv; S2a KubeRay container);
#   2) dependency isolation: ray[default]+DJ transitive pins clash with service-side pydantic/lance/boto3;
#   3) clean boundary: platform never imports DJ — only subprocess-invokes the dj-process binary (dj_fn seam).
# Ray lesson (spike 2026-06-10): never run Ray from a transient `uv run --with` env (py_executable
# is shipped to workers and hangs); use a persistent standalone venv (still uv-managed, not the main .venv).
set -euo pipefail
cd "$(dirname "$0")/.."
VENV=.dj-venv
if [ -x "${VENV}/bin/dj-process" ]; then
  echo "DJ venv ready: ${VENV}/bin/dj-process (rm ${VENV} to reinstall)"
  exit 0
fi
echo "building DJ venv at ${VENV} (py-data-juicer + ray[default] + pillow, ~93 pkgs, no torch) ..."
uv venv "${VENV}" --python 3.12
VIRTUAL_ENV="${PWD}/${VENV}" uv pip install 'py-data-juicer' 'ray[default]' 'pillow>=10'
echo "DJ venv ready: ${VENV}/bin/dj-process"
echo "data-pipeline default DJ_BIN points here (scripts/dev_services.sh / Makefile run-data-pipeline)."
