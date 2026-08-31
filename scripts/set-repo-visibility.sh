#!/usr/bin/env bash
# Portfolio Gate — bulk visibility for SuperfastSimon
# GitHub has NO bulk visibility endpoint. This loops PATCH /repos/{owner}/{repo}.
#
# Policy locked 2026-08-31:
#   KEEP_PUBLIC → public
#   everything else owned → private
#   Documents + Platform already private, untouched if already matching
#
# Token: classic `repo`  OR  fine-grained Administration:read+write on all repos
# Default: dry-run. Apply:  APPLY=1 ./scripts/set-repo-visibility.sh
set -euo pipefail

OWNER="${OWNER:-SuperfastSimon}"
KEEP_PUBLIC=(YieldLoop mvp-ship-gate)

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
need curl
need jq

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "GITHUB_TOKEN is required" >&2
  exit 1
fi

AUTH=( -H "Authorization: Bearer ${GITHUB_TOKEN}"
       -H "Accept: application/vnd.github+json"
       -H "X-GitHub-Api-Version: 2022-11-28" )

is_keep_public() {
  local n="$1"
  local k
  for k in "${KEEP_PUBLIC[@]}"; do
    [[ "$n" == "$k" ]] && return 0
  done
  return 1
}

echo "== list all repos for ${OWNER} =="
page=1
repos_json='[]'
while true; do
  chunk="$(curl -sS "${AUTH[@]}" \
    "https://api.github.com/user/repos?per_page=100&page=${page}&affiliation=owner")"
  if echo "$chunk" | jq -e '.message' >/dev/null 2>&1; then
    echo "API error listing repos:" >&2
    echo "$chunk" | jq -r '.message' >&2
    exit 1
  fi
  n="$(echo "$chunk" | jq 'length')"
  [[ "$n" == "0" ]] && break
  repos_json="$(jq -s 'add' <(echo "$repos_json") <(echo "$chunk"))"
  page=$((page + 1))
done

total="$(echo "$repos_json" | jq 'length')"
echo "found ${total} owned repos"
echo
printf '%-36s %-8s %-8s %s\n' REPO NOW TARGET ACTION
printf '%-36s %-8s %-8s %s\n' ---- --- ------ ------

changed=0
skipped=0
failed=0

while IFS=$'\t' read -r name vis; do
  if is_keep_public "$name"; then
    target=public
  else
    target=private
  fi

  if [[ "$vis" == "$target" ]]; then
    printf '%-36s %-8s %-8s %s\n' "$name" "$vis" "$target" skip
    skipped=$((skipped + 1))
    continue
  fi

  if [[ "${APPLY:-0}" != "1" ]]; then
    printf '%-36s %-8s %-8s %s\n' "$name" "$vis" "$target" "DRY-RUN would PATCH"
    changed=$((changed + 1))
    continue
  fi

  code="$(curl -sS -o /tmp/gh-vis-body.json -w '%{http_code}' \
    -X PATCH "${AUTH[@]}" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/${OWNER}/${name}" \
    -d "{\"visibility\":\"${target}\",\"private\":$([[ $target == private ]] && echo true || echo false)}")"

  if [[ "$code" == "200" ]]; then
    printf '%-36s %-8s %-8s %s\n' "$name" "$vis" "$target" "OK ${code}"
    changed=$((changed + 1))
  else
    printf '%-36s %-8s %-8s %s\n' "$name" "$vis" "$target" "FAIL ${code} $(jq -r '.message // empty' /tmp/gh-vis-body.json)"
    failed=$((failed + 1))
  fi
  sleep 0.25
done < <(echo "$repos_json" | jq -r '.[] | [.name, .visibility] | @tsv')

echo
echo "changed_or_planned=${changed} skipped=${skipped} failed=${failed} APPLY=${APPLY:-0}"
[[ "${APPLY:-0}" == "1" ]] || echo "Re-run with APPLY=1 to execute."
[[ "$failed" -eq 0 ]]
