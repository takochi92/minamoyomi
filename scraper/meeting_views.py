"""Compact meeting comparison; public records only, no prediction inputs."""
from datetime import datetime, timedelta
from pathlib import Path
from . import meeting


def feeds(site, data):
    if not hasattr(site, '_meeting_feeds'):
        day = getattr(site, 'idx', {}).get('date')
        site._meeting_feeds = meeting.load_feeds(data, day) if day else []
    return site._meeting_feeds


def context(site, data, day, jcd):
    return meeting.profile(feeds(site, data), getattr(site, 'idx', {}), day, jcd)


def index(site, data, load_history):
    if not hasattr(site, '_meeting_index'):
        idx = getattr(site, 'idx', {})
        periods = [f['start'] for f in feeds(site, data)]
        for v in idx.get('venues', []):
            b = meeting.bounds(idx.get('date', ''), v.get('day', ''))
            if b:
                periods.append(b[0])
        since = min(periods) if periods else idx.get('date', '99999999')
        saved = []
        for f in feeds(site,data):
            for record in f.get('exhibitions',{}).values():
                saved.append({'date':record['date'],'jcd':f['jcd'],'rno':record['rno'],
                              'racelist':{'boats':record['boats']},'before':{'boats':record['boats']}})
        for folder in sorted((Path(data)/'races').glob('*')):
            if not folder.is_dir() or not since <= folder.name <= idx.get('date', ''):
                continue
            for path in folder.glob('*.json'):
                import json
                try:
                    saved.append(json.loads(path.read_text(encoding='utf-8')))
                except (OSError, ValueError):
                    pass
        site._meeting_index = meeting.MeetingIndex(load_history(since=since) if periods else [], saved)
    return site._meeting_index


def late_exhibition(site, data, race):
    day, jcd = race.get('date'), race.get('jcd')
    if not day or not jcd:
        return None
    feed = context(site, data, day, jcd) or {}
    return feed.get('late_exhibition', {}).get(day+'-'+str(race.get('rno')))


def cache_inputs(site, data, day):
    """Attempt timestamps must not invalidate every historical HTML page."""
    return [{k: f.get(k) for k in ('jcd','start','end','title','precheck')} |
            {'exhibitions': {k:v for k,v in f.get('exhibitions',{}).items() if k[:8]<=day},
             'late_exhibition': {k:v for k,v in f.get('late_exhibition',{}).items() if k[:8]==day}}
            for f in feeds(site, data) if f['start']<=day<=f['end']]


def block(site, data, load_history, day, jcd, race, page, bt, esc, slug):
    feed = context(site, data, day, jcd)
    if not feed:
        return '<section class="panel"><h2>節間</h2><p class="sub">この節の開催期間を確認できていません。取得後に表示します。</p></section>'
    records = index(site, data, load_history)
    precheck = feed.get('precheck',{})
    start = datetime.strptime(feed['start'],'%Y%m%d')
    through = datetime.strptime(min(day,feed['end']),'%Y%m%d')
    days = [(start+timedelta(days=i)).strftime('%Y%m%d') for i in range((through-start).days+1)]
    rows, finishes = [], []
    for b in (race.get('racelist') or {}).get('boats', []):
        toban = str(b.get('toban',''))
        s = records.summary(jcd,toban,feed['start'],feed['end'],day)
        pre = precheck.get('rows',{}).get(toban,{})
        def cell(key, label, unit):
            value = s[key]
            text = f'{value:.2f}' if value is not None else '—'
            if key=='st' and value is not None:
                text=text.removeprefix('0')
            count = f'<small>{s[key+"_n"]}{unit}</small>' if value is not None else ''
            return f'<td data-label="{label}"><b>{text}</b>{count}</td>'
        name = f'<span class="meeting-boat">{bt(b["frame"])}<span>{esc(b.get("name",""))}</span></span>'
        pt = f'<b>{pre["time"]:.2f}</b>' if pre else '—'
        if pre and pre.get('motor_no') != b.get('motor_no'):
            pt += f'<small>{pre["motor_no"]}号機</small>'
        rows.append(f'<tr><th scope="row">{name}</th>{cell("ex","平均展示","回")}<td>{pt}</td>'
                    f'{cell("st","平均ST","走")}{cell("rank","ST順位","走")}</tr>')
        by_day={d:[] for d in days}
        for r in s['results']:
            label = str(r['place'])
            date = datetime.strptime(r['date'],'%Y%m%d').strftime('%m/%d')
            full_label = label+'着' if label.isdigit() else label
            description = f'{date} {r["rno"]}R {full_label}'
            text = f'<small>{r["rno"]}R</small><b>{esc(label)}</b>'
            cls = ' podium' if label in ('1','2','3') else (' incident' if not label.isdigit() else '')
            attrs = f'class="meeting-finish{cls}" title="{esc(description)}" aria-label="{esc(description)}"'
            if (Path(data)/'races'/r['date']/f'{jcd}{r["rno"]:02}.json').exists():
                url=page.u(f'race/{r["date"]}/{slug[jcd]}-{r["rno"]}.html#kekka')
                by_day[r['date']].append(f'<a {attrs} href="{url}">{text}</a>')
            else:
                by_day[r['date']].append(f'<span {attrs}>{text}</span>')
        cells=''.join('<td><div class="meeting-day-results">'+(''.join(by_day[d]) or '<span class="sub" aria-label="保存済み成績なし">—</span>')+'</div></td>' for d in days)
        finishes.append(f'<tr><th scope="row">{name}</th>{cells}</tr>')
    def md(value): return datetime.strptime(value,'%Y%m%d').strftime('%m/%d')
    sources=[]
    # Construct official URLs ourselves rather than trusting a stored URL in HTML.
    if precheck:
        sources.append(f'<a href="https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd={jcd}&amp;hd={day}" target="_blank" rel="noopener">公式の前検タイム</a>')
    return (f'<section class="panel meeting-panel"><h2>節間の比較</h2>'
            f'<p class="sub meeting-period">{md(feed["start"])}〜{md(feed["end"])} · {md(day)}までの保存済み記録</p>'
            '<table class="meeting-table"><thead><tr><th>艇・選手</th><th>平均<br>展示</th><th>前検</th><th>平均<br>ST</th><th>ST<br>順位</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '<details class="meeting-explain"><summary>集計の見方・出典</summary><p class="sub">'
            '平均展示・平均ST・ST順位は今節の保存済み公式記録を艇ろぐで集計。数字の下は集計数です。'
            'F・Lは平均STとST順位から除外。ST順位は6艇分を確認できたレースのみで、同タイミングは同順位です。'
            '欠けたデータは推定せず「—」。当日分は表示中のレース以降の結果も含みます。締切前の予想には使いません。'
            '前検時と使用モーターが異なる場合は前検時の号機を併記します。</p>'
            f'<p class="sub">{" · ".join(sources)}</p></details></section>'
            '<section class="panel meeting-results"><h2>今節成績</h2><p class="sub meeting-period">着順 · タップでレース結果</p>'
            '<div class="meeting-results-scroll"><table class="meeting-results-table"><thead><tr><th>艇・選手</th>'
            +''.join(f'<th scope="col">{md(d)}</th>' for d in days)+'</tr></thead>'
            +f'<tbody>{"".join(finishes)}</tbody></table></div></section>')
