#!/usr/bin/env bash
# Run from an independent shallow checkout of the merged source.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TEILOG_PREMIUM_FUNCTION_URL:?missing destination}"
: "${TEILOG_PREMIUM_PUBLISH_KEY:?missing publish key}"
state=$(git rev-parse --absolute-git-dir)
exec 9>"$state/teilog-premium.lock"
if ! flock -n 9; then
  echo 'Premium update already running'
  exit 0
fi
cutoff=$(TZ=Asia/Tokyo date -d yesterday +%Y%m%d)
stamp="$state/teilog-premium-published"
if [[ -f "$stamp" && $(<"$stamp") == "$cutoff" ]]; then
  exit 0
fi
git fetch --quiet --depth=1 origin main
# Use one immutable revision for all input and code paths.
git checkout --quiet --detach FETCH_HEAD
python3 -m scraper.premium_motor --through "$cutoff" --publish
printf '%s\n' "$cutoff" > "$stamp.tmp"
mv -- "$stamp.tmp" "$stamp"
