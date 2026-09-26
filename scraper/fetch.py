"""公式サイトへのアクセス。

GitHub Actions（米国）から公式サイトまでは1リクエスト約10秒かかる（2026/9/26 実測）。
そのため同時に数本（WORKERS）まで並行して取り、1回の実行は時間の上限（BUDGET 秒）で打ち切る。
取り切れなかった分は5分後の次の実行で続きから取る。リクエストの開始は INTERVAL 秒ずつずらす。
"""
from __future__ import annotations

import os
import threading
import time

import requests

BASE = "https://www.boatrace.jp/owpc/pc/race"
SITE_URL = os.environ.get("SITE_URL", "https://example.com")
UA = f"Mozilla/5.0 (compatible; BoatYosouBot/1.0; +{SITE_URL}/about.html)"
INTERVAL = float(os.environ.get("FETCH_INTERVAL", "0.5"))
BUDGET = float(os.environ.get("FETCH_BUDGET", "330"))
WORKERS = int(os.environ.get("FETCH_WORKERS", "6"))


class Fetcher:
    def __init__(self, max_requests: int = 400, budget: float | None = None):
        self.s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=WORKERS, pool_maxsize=WORKERS)
        self.s.mount("https://", adapter)
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ja"})
        self.count = 0
        self.max_requests = max_requests
        self.started = time.time()
        self.budget = BUDGET if budget is None else budget
        self._last = 0.0
        self._lock = threading.Lock()

    @property
    def exhausted(self) -> bool:
        return self.count >= self.max_requests or time.time() - self.started > self.budget

    def _slot(self):
        """リクエストの開始を INTERVAL 秒ずつずらす（並行でも一斉には送らない）"""
        with self._lock:
            if self.exhausted:
                raise RuntimeError("request budget exhausted")
            wait = self._last + INTERVAL - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.count += 1

    def get(self, page: str, **params) -> str:
        for attempt in range(2):
            self._slot()
            try:
                r = self.s.get(f"{BASE}/{page}", params=params, timeout=(10, 40))
                r.raise_for_status()
                r.encoding = "utf-8"
                return r.text
            except requests.RequestException:
                if attempt == 1:
                    raise
                time.sleep(2)
        raise RuntimeError("unreachable")

    def index(self, hd):
        return self.get("index", hd=hd)

    def racelist(self, jcd, rno, hd):
        return self.get("racelist", rno=rno, jcd=jcd, hd=hd)

    def beforeinfo(self, jcd, rno, hd):
        return self.get("beforeinfo", rno=rno, jcd=jcd, hd=hd)

    def result(self, jcd, rno, hd):
        return self.get("raceresult", rno=rno, jcd=jcd, hd=hd)

    def odds3t(self, jcd, rno, hd):
        return self.get("odds3t", rno=rno, jcd=jcd, hd=hd)

    def oddstf(self, jcd, rno, hd):
        return self.get("oddstf", rno=rno, jcd=jcd, hd=hd)

    def odds2tf(self, jcd, rno, hd):
        return self.get("odds2tf", rno=rno, jcd=jcd, hd=hd)

    def oriten(self, jcd, rno, hd):
        """オリジナル展示データ（一周・まわり足・直線など。各場が計測し BOATCAST が公開）。未公開なら None"""
        self._slot()
        try:
            r = self.s.get(f"https://race.boatcast.jp/txt/{jcd}/bc_oriten_{hd}_{jcd}_{int(rno):02d}.txt", timeout=20)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        r.encoding = "utf-8"
        return r.text
