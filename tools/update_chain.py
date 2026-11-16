"""update-races の中の監視：実行が終わるたびに、次の更新を自分で起動する。

GitHub のスケジュール実行は混んでいると抜ける（2026-11 は1日2〜5回しか起動しなかった）。
外の監視（Cloudflare の update-watchdog）に加えて、実行そのものが次をつなぐ。

- 動かす時間は外の監視と同じ（日本時間 7:00〜22:59 と 0:00〜1:59）
- 前の実行の開始から5分あける
- ほかの実行がもう待っている・走っている・直前に起動されたなら、起動しない（二重起動しない）
- 30分以上始まらないまま残った実行（ゴースト）は強制取り消しする

環境変数：GITHUB_TOKEN（actions: write）、GITHUB_REPOSITORY、GITHUB_RUN_ID、UPDATE_STARTED（開始の UNIX 秒）
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

WORKFLOW = 'update.yml'
CADENCE = 300            # 前の開始から5分
RECENT = 270             # これより新しい実行があれば、もう誰かが起動ずみ
FRESH_WAIT = 10 * 60     # 待ち状態でもこれより新しければ「起動待ち」とみなす
GHOST = 30 * 60          # 始まらないまま30分 → ゴースト
JST = timezone(timedelta(hours=9))


def operating(now: datetime) -> bool:
    hour = now.astimezone(JST).hour
    return hour < 2 or 7 <= hour < 23


def parse(at: str) -> float:
    return datetime.fromisoformat(at.replace('Z', '+00:00')).timestamp()


def decide(runs: list[dict], current_id: str, now: float) -> tuple[str, list[int]]:
    """('dispatch'|'skip-…', ゴーストの run id 一覧) を返す。"""
    ghosts, busy, recent = [], False, False
    for run in runs:
        if str(run.get('id')) == str(current_id):
            continue
        age = now - parse(run['created_at'])
        status = run.get('status')
        if status != 'completed' and status != 'in_progress' and age >= GHOST:
            ghosts.append(run['id'])
            continue
        if status == 'in_progress' or (status != 'completed' and age < FRESH_WAIT):
            busy = True
        if age < RECENT:
            recent = True
    if busy:
        return 'skip-busy', ghosts
    if recent:
        return 'skip-recent', ghosts
    return 'dispatch', ghosts


def api(path: str, method: str = 'GET', body: dict | None = None):
    repo = os.environ['GITHUB_REPOSITORY']
    request = urllib.request.Request(
        f'https://api.github.com/repos/{repo}{path}', method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                 'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN']})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def main() -> int:
    if not operating(datetime.now(timezone.utc)):
        print('chain: outside operating hours')
        return 0
    started = float(os.environ.get('UPDATE_STARTED') or time.time())
    wait = started + CADENCE - time.time()
    if wait > 0:
        time.sleep(min(wait, CADENCE))
    if not operating(datetime.now(timezone.utc)):
        print('chain: outside operating hours')
        return 0
    runs = api(f'/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=20')['workflow_runs']
    decision, ghosts = decide(runs, os.environ.get('GITHUB_RUN_ID', ''), time.time())
    for run_id in ghosts:
        try:
            api(f'/actions/runs/{run_id}/force-cancel', 'POST')
            print('chain: force-cancelled ghost run', run_id)
        except Exception as error:  # 取り消せなくても、起動は続ける
            print('chain: could not cancel ghost run', run_id, type(error).__name__)
    if decision == 'dispatch':
        api(f'/actions/workflows/{WORKFLOW}/dispatches', 'POST', {'ref': 'main'})
    print('chain:', decision)
    return 0


if __name__ == '__main__':
    sys.exit(main())
