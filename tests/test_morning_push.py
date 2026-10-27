from datetime import datetime

from tools.morning_push import JST, matches, payload, valid_subscription


def sample():
    feed={'date':'20261027','racers':{'1234':[
        ['平和島',1,'race/20261027/heiwajima-1.html','09:00',1],
        ['平和島',6,'race/20261027/heiwajima-6.html','13:00',4]],
        '5678':[['桐生',7,'race/20261027/kiryu-7.html','18:00',6]]}}
    return feed,{'1234':{'name':'選手A'},'5678':{'name':'選手B'}},datetime(2026,10,27,8,13,tzinfo=JST)


def test_explicit_frames_only_and_no_default_opt_in():
    feed,fav,now=sample()
    rows=matches(feed,fav,{'1234':[4],'5678':[6]},now)
    assert [(r['racer'],r['frame']) for r in rows]==[('1234',4),('5678',6)]
    assert matches(feed,fav,{},now)==[]
    assert matches(feed,fav,{'1234':[]},now)==[]
    assert matches(feed,{}, {'1234':[4]},now)==[]


def test_old_day_past_deadline_bad_paths_duplicates_and_invalid_frames():
    feed,fav,now=sample()
    assert len(matches(feed,fav,{'1234':[1,4]},now.replace(hour=10)))==1
    assert matches(feed,fav,{'1234':[True]},now)==[]
    assert matches(feed,fav,{'1234':[7]},now)==[]
    feed['racers']['1234']*=2
    assert len(matches(feed,fav,{'1234':[4]},now))==1
    feed['racers']['1234'][1][2]='https://evil.example/'
    assert matches(feed,fav,{'1234':[4]},now)==[]
    feed['date']='20261026'
    assert matches(feed,fav,{'1234':[1]},now)==[]


def test_endpoint_restrictions_prevent_arbitrary_network_calls():
    s={'endpoint':'https://fcm.googleapis.com/fcm/send/abc','keys':{'p256dh':'a'*87,'auth':'b'*22}}
    assert valid_subscription(s)
    for url in ['http://fcm.googleapis.com/x','https://127.0.0.1/x','https://fcm.googleapis.com.evil.example/x',
                'https://user@fcm.googleapis.com/x','https://fcm.googleapis.com:444/x','https://fcm.googleapis.com/x#fragment']:
        assert not valid_subscription(dict(s,endpoint=url))


def test_digest_links_to_private_list_and_does_not_include_endpoints():
    feed,fav,now=sample();rows=matches(feed,fav,{'1234':[4]},now)
    p=payload(rows,feed['date'])
    assert p['url']=='/mynote?morning=20261027'
    assert '4号艇' in p['body'] and '13:00' in p['body']
    assert p['tag']=='teilog-morning-20261027'


def test_runner_claims_once_and_does_not_log_private_payload(monkeypatch, capsys):
    import json
    import sys
    import types
    from tools import morning_push as m
    feed,fav,now=sample()
    subscription={'endpoint':'https://fcm.googleapis.com/fcm/send/private-only','keys':{'p256dh':'a'*87,'auth':'b'*22}}
    device={'id':'00000000-0000-4000-8000-000000000001','user_id':'00000000-0000-4000-8000-000000000002',
            'revision':1,'rules':{'1234':[4]},'subscription':subscription}
    claims=set();sent=[];statuses=[]
    class DB:
        def __init__(self,*args):pass
        def request(self,method,path,**kw):
            if method=='GET':return [{'data':{'fav':fav}}] if path.startswith('teilog_notes') else [device]
            if path=='rpc/teilog_claim_push':
                key=(kw['json']['target_device'],kw['json']['target_day'])
                if key in claims:return False
                claims.add(key);return True
            statuses.append(kw['json']);return None
    class PushError(Exception):pass
    monkeypatch.setitem(sys.modules,'pywebpush',types.SimpleNamespace(webpush=lambda **kw:sent.append(kw),WebPushException=PushError))
    monkeypatch.setattr(m,'Store',DB)
    monkeypatch.setattr(m.requests,'get',lambda *a,**kw:types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:feed))
    for k in ('PUSH_SUPABASE_URL','PUSH_SUPABASE_SERVICE_KEY','PUSH_VAPID_PRIVATE_KEY'):monkeypatch.setenv(k,'test-only')
    m.run(now);m.run(now)
    assert len(sent)==1 and statuses==[{'status':'sent'}]
    assert json.loads(sent[0]['data'])['day']==feed['date']
    assert sent[0]['timeout']==20 and 0<sent[0]['ttl']<=3600
    output=capsys.readouterr().out
    assert 'private-only' not in output and '選手A' not in output and device['user_id'] not in output


def test_delayed_runner_never_delivers_at_noon(monkeypatch,capsys):
    from tools import morning_push as m
    m.run(datetime(2026,10,27,12,0,tzinfo=JST))
    assert 'skipped' in capsys.readouterr().out
