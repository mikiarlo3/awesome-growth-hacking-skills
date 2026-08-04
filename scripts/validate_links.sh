#!/usr/bin/env bash
set -euo pipefail

repo_dir="${1:-.}"
readme="$repo_dir/README.md"
output="$repo_dir/.link-check.tsv"

if [[ ! -f "$readme" ]]; then
  printf 'README not found: %s\n' "$readme" >&2
  exit 1
fi

mapfile -t urls < <(
  grep -oE 'https?://[^) >"]+' "$readme" \
    | sed 's/[.,]$//' \
    | sort -u
)

: > "$output"
for url in "${urls[@]}"; do
  status="$(curl -L -A 'Mozilla/5.0 (compatible; enso-bot-link-check/1.0)' -sS -o /dev/null -w '%{http_code}' --connect-timeout 10 --max-time 25 "$url" || true)"
  if [[ -z "$status" || "$status" == "000" ]]; then
    status="000"
  fi
  printf '%s\t%s\n' "$status" "$url" >> "$output"
done

printf '%s\n' '--- STATUS SUMMARY ---'
awk -F '\t' '{count[$1]++} END {for (code in count) print code, count[code]}' "$output" | sort -n
printf '%s\n' '--- NON-2XX/3XX RESULTS ---'
awk -F '\t' '$1 !~ /^(200|301|302|303|307|308)$/ {print}' "$output" || true
printf '%s\n' '--- VALIDATED COUNT ---'
wc -l "$output"
