#!/usr/bin/env bash
# Entry point for automatic MVP ship-gate validation.
# Usage:
#   validate.sh <project-root> [light|full]
#   validate.sh --selftest
# Env:
#   MVP_GATE_FORMAT=text|json|github|junit
#   MVP_GATE_REPORT=/path/to/report.json
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${DIR}/mvp_validate.py"
FORMAT="${MVP_GATE_FORMAT:-text}"
REPORT="${MVP_GATE_REPORT:-}"

if [[ "${1:-}" == "--selftest" ]]; then
  FIX_OK="${DIR}/fixtures/ok-static"
  FIX_BAD="${DIR}/fixtures/bad-web"
  echo "== selftest PASS fixture (expect 0) =="
  set +e
  python3 "$PY" "$FIX_OK" --mode full
  ok_ec=$?
  echo "== selftest FAIL fixture (expect 1) =="
  python3 "$PY" "$FIX_BAD" --mode full
  bad_ec=$?
  echo "== selftest github annotations on FAIL fixture =="
  python3 "$PY" "$FIX_BAD" --mode full --format github >/tmp/mvp-gate-gh.txt
  gh_ec=$?
  set -e
  if [[ "$ok_ec" -ne 0 ]]; then
    echo "SELFTEST FAIL: ok-static should PASS" >&2
    exit 1
  fi
  if [[ "$bad_ec" -ne 1 ]]; then
    echo "SELFTEST FAIL: bad-web should FAIL with exit 1 (got $bad_ec)" >&2
    exit 1
  fi
  if [[ "$gh_ec" -ne 1 ]] || ! grep -q '::error file=' /tmp/mvp-gate-gh.txt; then
    echo "SELFTEST FAIL: github format should emit ::error annotations" >&2
    exit 1
  fi
  echo "SELFTEST PASS"
  exit 0
fi

ROOT="${1:-.}"
MODE="${2:-full}"
if [[ "$MODE" != "light" && "$MODE" != "full" ]]; then
  echo "Usage: validate.sh <project-root> [light|full]" >&2
  exit 2
fi

extra=()
if [[ -n "$REPORT" ]]; then
  extra+=(--report "$REPORT")
fi
set +e
python3 "$PY" "$ROOT" --mode "$MODE" --format "$FORMAT" "${extra[@]}"
ec=$?
set -e
if [[ "$ec" -eq 0 || "$ec" -eq 1 ]]; then
  exit "$ec"
fi
echo "MVP ship-gate harness error (exit $ec)" >&2
exit 2
