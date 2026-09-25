"""公式サイトへのアクセス。サーバーに負荷をかけないよう 1 リクエストごとに間隔を空ける。"""
from __future__ import annotations

import os
import time

import requests

BASE = "https://www.boatrace.jp/owpc/pc/race"
SITE_URL = os.environ.get("SITE_URL", "https://example.com")
UA = f"Mozilla/5.0 (compatible; BoatYosouBot/1.0; +{SITE_URL}/about.html)"
INTERVAL = float(os.environ.get("FETCH_INTERVAL", "1.0"))


class Fetcher:
    def __init__(self, max_requests: int = 120):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ja"})
        self.count = 0
        self.max_requests = max_requests
        self._last = 0.0

    @property
    def exhausted(self) -> bool:
        return self.count >= self.max_requests

    def get(self, page: str, **params) -> str:
        if self.exhausted:
            raise RuntimeError("request budget exhausted")
        wait = INTERVAL - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            try:
                self._last = time.time()
                self.count += 1
                r = self.s.get(f"{BASE}/{page}", params=params, timeout=20)
                r.raise_for_status()
                r.encoding = "utf-8"
                return r.text
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
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
