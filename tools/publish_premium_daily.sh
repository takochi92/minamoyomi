#!/usr/bin/env bash
# Use a dedicated checkout. Cron may retry after midnight until every result is available.
set -euo pipefail
cd "$(dirname "$0")/.."
state=$(git rev-parse --absolute-git-dir)
exec 9>"$state/teilog-premium.lock"
if ! flock -n 9; then
  echo 'Premium update already running'
  exit 0
fi
cutoff=$(TZ=Asia/Tokyo date -d yesterday +%Y%m%d)
mode=preview
if [[ -n "${TEILOG_PREMIUM_FUNCTION_URL:-}" && -n "${TEILOG_PREMIUM_PUBLISH_KEY:-}" ]]; then
  mode=publish
fi
stamp="$state/teilog-premium-$mode"
if [[ -f "$stamp" && $(<"$stamp") == "$cutoff" ]]; then
  exit 0
fi
git fetch --quiet --depth=1 origin main
# The archive below modifies tracked files in this dedicated checkout.
git checkout --quiet --force --detach FETCH_HEAD
# Archive locally. If no new result appears in the public input, the production
# check fails and the next run retries the same cutoff with fresh input.
python3 -m scraper.research_snapshot --date "$cutoff"
out="private/premium/$cutoff.json"
args=(--through "$cutoff" --output "$out" --require-complete)
if [[ "$mode" == publish ]]; then
  args+=(--publish)
fi
python3 -m scraper.premium_motor "${args[@]}"
printf '%s\n' "$cutoff" > "$stamp.tmp"
mv -- "$stamp.tmp" "$stamp"
