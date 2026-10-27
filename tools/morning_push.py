"""Morning digest. No endpoints, account IDs or payloads in logs or artifacts."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

JST = timezone(timedelta(hours=9))
PUSH_HOST = re.compile(r'^(?:fcm\.googleapis\.com|updates\.push\.services\.mozilla\.com|web\.push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com)$')


def valid_subscription(subscription):
    try:
        url = urlsplit(subscription['endpoint'])
        keys = subscription['keys']
        return (url.scheme == 'https' and not url.username and not url.password and url.port is None
                and bool(PUSH_HOST.fullmatch(url.hostname or '')) and bool(url.path.strip('/'))
                and not url.fragment and len(subscription['endpoint']) <= 4096
                and bool(re.fullmatch(r'[A-Za-z0-9_-]{87,88}', keys['p256dh']))
                and bool(re.fullmatch(r'[A-Za-z0-9_-]{22,24}', keys['auth'])))
    except (KeyError, TypeError, ValueError):
        return False


def matches(feed, favorites, rules, now):
    """Only explicitly opted-in racers/frames, today's still-future programmes."""
    if feed.get('date') != now.strftime('%Y%m%d'):
        return []
    found = {}
    for racer in sorted(set(favorites) & set(rules)):
        frames = rules[racer]
        if not isinstance(frames, list) or any(type(f) is not int or f not in range(1,7) for f in frames):
            continue
        for race in feed.get('racers', {}).get(racer, []):
            if not isinstance(race, list) or len(race) != 5:
                continue
            venue, rno, path, deadline, frame = race
            if frame not in frames or type(frame) is not int or type(rno) is not int or rno not in range(1,13):
                continue
            if not re.fullmatch(r'race/'+feed['date']+r'/[a-z]+-'+str(rno)+r'\.html', str(path)):
                continue
            try:
                when = datetime.strptime(feed['date']+' '+deadline,'%Y%m%d %H:%M').replace(tzinfo=JST)
            except (ValueError, TypeError):
                continue
            if when <= now:
                continue
            name = str(favorites[racer].get('name', racer))[:30]
            found[(racer,path)] = {'racer':racer,'name':name,'venue':str(venue)[:15],
                                  'rno':rno,'deadline':deadline,'frame':frame,'path':path}
    return sorted(found.values(), key=lambda r:(r['deadline'],r['path'],r['racer']))


def payload(rows, day):
    lines=[f"{r['name']} {r['venue']}{r['rno']}R {r['frame']}号艇 {r['deadline']}" for r in rows[:4]]
    if len(rows)>4:
        lines.append(f'ほか{len(rows)-4}件。タップで一覧')
    return {'title':f'お気に入りの出走 {len(rows)}件', 'body':'\n'.join(lines),
            'url':'/mynote?morning='+day,'tag':'teilog-morning-'+day,'day':day}


class Store:
    def __init__(self, url, key):
        self.url=url.rstrip('/')+'/rest/v1/'
        self.session=requests.Session()
        self.session.headers.update({'apikey':key,'Authorization':'Bearer '+key})

    def request(self, method, path, **kwargs):
        r=self.session.request(method,self.url+path,timeout=30,allow_redirects=False,**kwargs)
        if not r.ok:
            raise RuntimeError('Notification database request failed')
        return r.json() if r.content else None


def run(now=None):
    now=now or datetime.now(JST)
    # Delayed jobs do not deliver a "morning" digest at noon or the next day.
    if not 8<=now.hour<10:
        print('Outside morning delivery window; skipped'); return
    from pywebpush import webpush, WebPushException
    store=Store(os.environ['PUSH_SUPABASE_URL'],os.environ['PUSH_SUPABASE_SERVICE_KEY'])
    r=requests.get('https://teilog.com/fav-today.json',timeout=30)
    r.raise_for_status(); feed=r.json()
    if feed.get('date')!=now.strftime('%Y%m%d'):
        raise RuntimeError('Published programme is not current; no notifications sent')
    day=now.date().isoformat(); sent=failed=0; cursor=''
    while True:
        devices=store.request('GET','teilog_push_devices?enabled=eq.true&order=id&limit=500'+('&id=gt.'+cursor if cursor else ''))
        if not devices: break
        cursor=devices[-1]['id']
        for device in devices:
            if not valid_subscription(device['subscription']): continue
            notes=store.request('GET','teilog_notes?select=data&user_id=eq.'+device['user_id'])
            rows=matches(feed, (notes[0]['data'].get('fav') or {}) if notes else {},device['rules'],now)
            if not rows: continue
            # Atomic claim, fail closed on ambiguous delivery; never repeat that day's digest.
            if not store.request('POST','rpc/teilog_claim_push',json={'target_device':device['id'],'target_day':day,'expected_revision':device['revision']}): continue
            state='failed'
            try:
                webpush(subscription_info=device['subscription'],data=json.dumps(payload(rows,feed['date']),ensure_ascii=False),
                        vapid_private_key=os.environ['PUSH_VAPID_PRIVATE_KEY'],vapid_claims={'sub':'https://teilog.com'},
                        ttl=min(3600,max(0,int((now.replace(hour=10,minute=0,second=0)-now).total_seconds()))),timeout=20)
                state='sent'; sent+=1
            except WebPushException as e:
                failed+=1
                if e.response is not None and e.response.status_code in (404,410):
                    state='expired'
                    store.request('PATCH','teilog_push_devices?id=eq.'+device['id'],json={'enabled':False})
            except Exception:
                failed+=1
            store.request('PATCH',f"teilog_push_deliveries?device_id=eq.{device['id']}&day=eq.{day}",json={'status':state})
        if len(devices)<500: break
    print(f'Morning delivery finished: sent={sent}, failed={failed}')


if __name__=='__main__':
    try: run()
    except Exception:
        # Avoid leaking private push endpoint URLs from exceptions/tracebacks.
        print('Morning delivery stopped; check configuration and service status. No private data logged.')
        raise SystemExit(1)
