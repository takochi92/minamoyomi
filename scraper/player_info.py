"""Display-only player information; never fed into betting predictions."""
import json
from datetime import datetime
from html import escape as e
from urllib.parse import urlparse
from .season_watch import period

GP_GUIDE='https://www.boatrace.jp/owsp/sp/extra/enjoy/guide/level1/l1_01_02_03.html'


def date(value):
    return f'{value[:4]}/{value[4:6]}/{value[6:8]}' if value else '未確認'


def payload(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')


def official_url(url):
    try:
        p=urlparse(url)
        return p.scheme=='https' and p.hostname in {'www.boatrace.jp','boatrace.jp','www.boatrace-tsu.com','www.boatrace-hamanako.jp','omurakyotei.jp'}
    except (TypeError,ValueError):
        return False


def programme_snapshots(races, today):
    out={}
    for race in races:
        day=race.get('date','')
        if not re_date(day) or day>today:
            continue
        for boat in (race.get('racelist') or {}).get('boats',[]):
            t=str(boat.get('toban',''))
            if not (len(t)==4 and t.isdigit()) or boat.get('f_known') is not True or type(boat.get('f')) is not int:
                continue
            row={'date':day,'jcd':race['jcd'],'rno':race['rno'],'f':boat['f']}
            if t not in out or (day,row['rno'])>(out[t]['date'],out[t]['rno']):out[t]=row
    return out


def re_date(value):
    try:
        return len(value)==8 and datetime.strptime(value,'%Y%m%d').strftime('%Y%m%d')==value
    except (ValueError,TypeError):
        return False


def build_f_report(report, snapshots, leaves, today, racers):
    current=period(today)
    histories={p['toban']:p for p in report.get('f_players',[]) if p.get('toban')}
    rests={}
    for r in leaves.get('records',[]):
        if official_url(r.get('source')):
            rests.setdefault(r['toban'],[]).append(r)
    ids=set(histories)|set(snapshots)|set(rests)
    rows=[]
    rollover_ready=not report.get('f_preparing',True) and report.get('period')==current
    for t in sorted(ids):
        info=racers.get(t,{})
        history=histories.get(t,{})
        snapshot=snapshots.get(t)
        if snapshot and not current['from']<=snapshot.get('date','')<=today:
            snapshot=None
        f=snapshot.get('f') if snapshot else None
        if type(f) is not int or not 0<=f<=9:
            f=None;snapshot=None
        rest=rests.get(t,[])
        if not history and not rest and not f:
            continue
        previous_events=[x for x in history.get('events',[]) if report.get('f_period',{}).get('from','')<=x.get('date','')<current['from']]
        hidden=bool(rollover_ready and f==0 and previous_events and not history.get('current_f_known'))
        row={'toban':t,'name':info.get('name') or history.get('name') or (rest[0].get('name') if rest else t),
             'kana':info.get('kana',''),'branch':info.get('branch') or history.get('branch',''),
             'f':f,'programme':snapshot,'history_count':len(history.get('events',[])),
             'last_f':history.get('last_f',''),'rests':rest,'rollover':hidden}
        rows.append(row)
    return {'kind':'f','as_of':today,'through':report.get('through',''),'period':report.get('f_period',{}),
            'new_start':report.get('new_start',''),'preparing':report.get('f_preparing',True),'rows':rows}


def hub(page, prizes):
    stamp=f'公式掲載 {date(prizes.get("through"))}まで' if prizes else '公式データを確認中'
    return f'''<h1>選手情報</h1><p class="sub">F・休み、期末勝率、年末の賞金争いをまとめて確認。</p>
<div class="pi-hub">
<a href="{page.u('players-f.html')}"><h2>F・休みの確認</h2><p>出走表のF本数・F2以上、公式記載の未消化休み、期またぎFの確認。</p><span>選手名・登録番号で検索 →</span></a>
<a href="{page.u('database/season.html')}"><h2>期末勝率・A1/A2ボーダー</h2><p>現在の参考勝率、あと何走で何点・何着が必要かを確認。</p><span>期末の条件を見る →</span></a>
<a href="{page.u('players-prizes.html')}"><h2>賞金ランキング・グランプリ</h2><p>獲得賞金、6位・18位との差額、年末のグランプリ情報。</p><span>{e(stamp)} →</span></a>
</div><p class="sub"><a href="{page.u('racer/index.html')}">通常の選手・モーター検索 →</a></p>'''


def f_page(page, data):
    upcoming=(f'<p class="sub">次の期替わりは{date(data.get("new_start"))}。期初のF0表示との比較は期替わり後からです。</p>' if data.get('preparing') else '')
    return f'''<h1>F・休みの確認</h1><p class="sub">保存した公式出走表と、公式資料で確認できた休みを検索できます。</p>
<p class="pi-note">F本数と休みの未消化は別です。全国全選手の未消化一覧ではありません。記載のない選手を「消化済み」とは判定しません。</p>
<div class="pi-controls"><input id="pi-q" type="search" placeholder="選手名・登録番号・支部" aria-label="選手を検索">
<select id="pi-filter" aria-label="F情報の絞り込み"><option value="f">出走表にFあり</option><option value="f2">出走表にF2以上</option><option value="leave">公式の未消化休み記載</option><option value="rollover">期またぎFの確認</option><option value="all">保存F歴・確認資料すべて</option></select></div>
<details class="more"><summary>期またぎF（通称「隠れF」）について</summary><p>期替わり後の出走表がF0でも、前期のF歴がある選手を確認する欄です。これだけで休みが未消化とは断定できません。休みは公式資料の確認日と記載内容で別に確認します。</p>{upcoming}</details>
<p class="sub">F履歴は{date(data.get('through'))}の保存結果まで。出走表のF本数は各選手に確認日を表示します。</p>
<p id="pi-count" class="sub" role="status"></p><div id="pi-list" class="pi-list"></div><button id="pi-more" class="btn" type="button" hidden>もっと見る</button>
<script id="pi-data" type="application/json">{payload(data)}</script><script src="{page.asset('player-info.js')}" defer></script>'''


def prize_page(page, report, today, events):
    intro='<h1>賞金ランキング・グランプリ</h1>'
    if not report:
        return intro+'<p>公式賞金ランキングを確認中です。</p>'
    rows=report.get('players',[])
    by_rank={r['rank']:r for r in rows}
    eighteenth=by_rank.get(18,{}).get('amount')
    sixth=by_rank.get(6,{}).get('amount')
    data={'kind':'prizes','year':report['year'],'through':report['through'],'source':report['source'],
          'rows':[{**r,'gap18':r['amount']-eighteenth if eighteenth is not None else None,'gap6':r['amount']-sixth if sixth is not None else None} for r in rows]}
    event=next((x for doc in events for x in doc.get('events',[]) if x.get('title')=='グランプリ' and x['from'][:4]==str(report['year'])),None)
    schedule=(f'<p>{date(event["from"])}〜{date(event["through"])} ／ 大村</p>' if event and event.get('jcd')=='24' else '')
    age=(datetime.strptime(today,'%Y%m%d')-datetime.strptime(report['through'],'%Y%m%d')).days
    warning='<p class="pi-note">公式掲載日から7日以上経過しています。最新の選出発表も確認してください。</p>' if age>7 else ''
    source=(f'<a href="{e(report["source"],quote=True)}" target="_blank" rel="noopener">大村公式の賞金ランキング ↗</a>' if official_url(report.get('source')) else '出典確認中')
    return intro+f'''<p class="sub">{report['year']}年 ／ {date(report['from'])}〜{date(report['through'])}の公式掲載分。日次で確認します。</p>{warning}
<section class="panel pi-gp"><h2>年末のグランプリ</h2>{schedule}<p>賞金18位ラインとの位置関係を確認できます。掲載順位だけで出場確定とは判断しません。出場資格・欠場などを含む正式発表を優先します。</p><p class="sub"><a href="{GP_GUIDE}" target="_blank" rel="noopener">公式のグランプリ解説 ↗</a> ／ {source}</p></section>
<div class="pi-controls"><input id="pi-q" type="search" placeholder="選手名・登録番号" aria-label="賞金ランキングの選手を検索"><select id="pi-filter" aria-label="賞金順位の絞り込み"><option value="all">掲載順位すべて</option><option value="border">18位前後（13〜24位）</option><option value="top18">上位18位</option><option value="top6">上位6位</option></select></div>
<p class="sub">差額は同じ掲載時点の6位・18位との比較です。最終ボーダーの予測額ではありません。</p>
<p id="pi-count" class="sub" role="status"></p><div id="pi-list" class="pi-list"></div><button id="pi-more" class="btn" type="button" hidden>もっと見る</button>
<script id="pi-data" type="application/json">{payload(data)}</script><script src="{page.asset('player-info.js')}" defer></script>'''
