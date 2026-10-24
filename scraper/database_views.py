"""Public official-data catalogue; separate from recommendations and results ROI."""
from __future__ import annotations
import html, json
from datetime import datetime
from collections import defaultdict
from . import racer_database as rd
from .database_sources import BASE, read_json

e=lambda x:html.escape(str(x if x is not None else '—'),quote=True)


def matrix(headers,rows):
    return '<table class="rv-matrix"><thead><tr>'+''.join('<th>'+e(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+(''.join('<tr>'+''.join(('<th scope="row">' if i==0 else '<td>')+str(x)+('</th>' if i==0 else '</td>') for i,x in enumerate(row))+'</tr>' for row in rows) or '<tr><td colspan="'+str(len(headers))+'">該当する保存記録はありません</td></tr>')+'</tbody></table>'


def period_label(term):return f'{term["year"]}年'+('前期' if term['half']==1 else '後期')


def birth_date(stats):
    value=stats.get('birth_date','');offset={'M':1867,'T':1911,'S':1925,'H':1988,'R':2018}.get(stats.get('birth_era'))
    if offset is None or len(value)!=6 or not value.isdigit():return '未確認'
    try:return datetime(offset+int(value[:2]),int(value[2:4]),int(value[4:])).strftime('%Y/%m/%d')
    except ValueError:return '未確認'


def period_panel(terms,as_of=None):
    body='<p class="sub">適用期ごとの公式公表値です。着順点による勝率と、1着になった割合は異なります。前期は1〜6月、後期は7〜12月の適用。各期の審査対象期間を併記しています。</p>'
    if as_of and terms:
        year=int(as_of[:4]);half=1 if int(as_of[4:6])<=6 else 2
        upcoming=(year,2) if half==1 else (year+1,1)
        applied=[]
        for label,key in [('現適用',(year,half)),('次期',upcoming)]:
            term=next((t for t in terms if (t['year'],t['half'])==key),None)
            s=term['stats'] if term else None
            applied.append([label+'<small>'+str(key[0])+'年'+('前期' if key[1]==1 else '後期')+'</small>',f'{s["win"]:.2f}' if s else '未公表・未収録',f'{s["top2"]:.1f}%' if s else '—',str(s['starts']) if s else '—'])
        body+=matrix(['適用','公式勝率','2連対率','出走'],applied)
    for term in reversed(terms):
        s=term['stats'];n=s['starts']
        cards=matrix(['公式勝率','2連対率','出走','優出／優勝'],[[e(f'{s["win"]:.2f}'),e(f'{s["top2"]:.1f}%'),str(n),f'{s["finals"]}／{s["titles"]}']])
        cards+='<p class="sub">生年月日 '+birth_date(s)+' · 出身地 '+e(s.get('birthplace'))+'（当期の公式掲載値）</p>'
        courses=[];acc=[]
        for c,m in enumerate(s['courses'],1):
            p=m['places'];nn=m['entries']
            courses.append([f'{c}コース<small>{nn}走</small>',str(p[0]),str(p[1]),str(p[2])])
            a=m['accidents'];acc.append([str(c),str(sum(x or 0 for x in p[3:])),f'{a["F"]}／{(a["L0"] or 0)+(a["L1"] or 0)}',e(f'{m["st"]:.2f}')])
        body+=f'<details class="panel db-term"><summary><b>{period_label(term)}</b><span>{e(s["class"])} · 勝率 {s["win"]:.2f} · {n}走</span></summary><p class="sub">対象：{rd.date(term["from"])}〜{rd.date(term["through"])}<br>当時の掲載名：{e(s["name"])} · {e(s.get("branch") or s.get("location"))}{"（当時の住所。支部ではありません）" if s.get("location") else "支部"}</p>{cards}<h3>進入コース別の着順回数</h3>{matrix(["コース","1着","2着","3着"],courses)}{matrix(["コース","4〜6着","F／L","平均ST"],acc)}<details><summary>4・5・6着と事故内訳</summary>{matrix(["コース","4着","5着","6着"],[[str(c),*[str(v) for v in m["places"][3:]]] for c,m in enumerate(s["courses"],1)])}<p class="sub">'+e(' ／ '.join(f'{c}コース '+', '.join(f'{k}:{v}' for k,v in m['accidents'].items()) for c,m in enumerate(s['courses'],1)))+'</p><p>進入コースなし：'+e(' ／ '.join(f'{k}:{v}' for k,v in s.get('no_course_accidents',{}).items()) or '未収録')+'</p></details>'+matrix(['コース','公式2連対','平均ST','平均ST順'],[[str(c),f'{m["top2"]:.1f}%',f'{m["st"]:.2f}',f'{m["st_rank"]:.2f}'] for c,m in enumerate(s['courses'],1)])+f'<p class="sub">平均ST {s["st"]:.2f} · {e(s.get("ki"))}期 · {e(s.get("age"))}歳（当期時点） · {e(s.get("height"))}cm · {e(s.get("weight"))}kg · {e(s.get("blood"))}型</p><p class="sub">直前3期の級：{e(" / ".join(s.get("prior_classes",[])) or "未収録")} · 能力指数：{e(s.get("prior_ability"))} → {e(s.get("ability"))}</p><a href="{e(term["source"])}">公式の期別成績ファイル</a></details>'
    return rd.section('公式期別成績',body if terms else '<p>この選手の公式期別ファイルは未収録です。</p>')


def titles_panel(events,toban,venues):
    rows=[]
    for ev in events:
        f=ev['final'];win=toban in f['winners']
        rows.append([rd.date(f['date'])+'<small>'+e(venues.get(ev['venue'],{}).get('name',ev['venue']))+(' '+str(f['race'])+'R' if f.get('race') else '')+'</small>',e(ev['grade'] or '格付未確認'),('<b class="db-gold">優勝</b>' if win else '優出')+'<small>'+e(ev['title'])+'</small>'])
    return rd.section('保存結果から確認できた優勝・優出',matrix(['日付・場','格付','結果・開催名'],rows),'公式Kファイルで「優勝戦」を確認できたレースのみ。準優勝戦は含めません。格付の記載が確認できない開催は未確認と表示します。生涯の優勝回数やSG出場回数の一覧ではありません。公式期別の優出・優勝回数も参照してください。')


def official_finals_panel(records):
    rows=[]
    for r in records:
        url='../database/champion-'+r['category']+'-'+r['number']+'.html'
        place=str(r.get('place') or '')
        result='優勝' if place=='1' else place+'着' if place.isdigit() else place or '記載なし'
        rows.append([rd.date(r['date'])+'<small>'+e(r['venue'])+'</small>',e(r['name'])+'<small>'+e(r['group'])+'</small>',f'<a href="{url}">'+e(result)+'</a>'])
    return rd.section('公式SG・PG1・G1記録集の決勝履歴',matrix(['日付・場','大会・記録集区分','結果'],rows),'公式記録集の決勝出走表で登番を照合した記録です。大会の記録集区分は、過去の開催当時の格付と異なる場合があります。全SG出場回数とは異なり、予選のみの出場は含みません。未取得の大会を0回とは扱いません。')


def catalog_pages(site,Page,venues):
    catalog=read_json(BASE/'catalog.json.gz')
    if not catalog:return
    from .database_build import periods
    terms=periods();summary=read_json(BASE/'summary.json.gz',{});roster={**catalog['roster'],**site.racers}
    vn=lambda j:venues.get(j,{}).get('name',j)
    name=lambda t:f'<a href="../racer/{e(t)}.html">{e(roster.get(t,{}).get("name",t))}</a>'
    def put(path,title,body):
        p=Page('database/'+path)
        back='<nav class="db-nav"><a href="index.html">データバンク</a><a href="../racer/index.html">選手検索</a><a href="coverage.html">収録状況</a></nav>'
        site.put(p.path,p.render(title+'｜艇ろぐ',title+'。公式成績の保存分を期間・件数つきで掲載。',f'<link rel="stylesheet" href="../racer.css">{back}<h1>{e(title)}</h1>{body}',[('database/index.html','データバンク'),('',title)]))
    def cards(items):return '<div class="db-cards">'+''.join(f'<a class="panel" href="{e(url)}"><b>{e(title)}</b><span>{e(note)}</span></a>' for url,title,note in items)+'</div>'
    stats=f'<div class="rd-summary db-summary"><div><span>掲載選手</span><strong>{len(roster):,}</strong><small>過去掲載選手を含む</small></div><div><span>公式期別</span><strong>{len(terms)}期</strong><small>公式公表ファイル</small></div><div><span>保存結果</span><strong>{catalog["races"]:,}</strong><small>レース</small></div><div><span>最終結果日</span><strong>{rd.date(catalog["through"])[5:]}</strong><small>{catalog["through"][:4]}年</small></div></div>'
    put('index.html','選手データバンク',f'<p>選手の得意コース、過去の期別成績、場の傾向を、出走数と期間を確かめながら比較できます。</p>{stats}'+cards([
        ('../racer/index.html','全選手を探す','名前・登録番号・支部・養成期で検索'),('periods.html','公式期別成績','級別・勝率・連対率・コース別着順・事故'),
        ('branches.html','支部別','各期の所属選手と実績'),('terms.html','養成期別','同期の選手と各期の成績'),('venues.html','場別データ','コース・決まり手・配当分布'),
        ('events.html','優勝戦・開催記録','確認できた優勝者と優出選手'),('championships.html','SG・PG1・G1公式記録集','歴代優勝者・決勝出走表・節間成績'),('rankings.html','コース別ランキング','直近90日・15走以上の実測1着率'),
        ('records.html','高配当・同着・スタート事故','保存結果の記録一覧'),('races.html','全保存レースを探す','月・場・万舟・F/L・同着で検索'),('../motor.html','モーター機歴','交換周期を考慮した機歴と乗り手'),
        ('equipment.html','ボート・モーター公式値','出走表に掲載された2連対・3連対率'),('coverage.html','収録範囲と更新状況','取得済み・不足・未確認を公開')]))
    put('periods.html','公式期別の一覧',rd.section('適用期と審査対象期間',matrix(['適用期','対象期間','掲載人数'],[[e(period_label(t)),rd.date(t['from'])+'<small>〜'+rd.date(t['through'])+'</small>',f'{len(t["players"]):,}人'] for t in reversed(terms)]))+'<p>各選手の「公式期別」タブで、全収録期の詳細を確認できます。次期分は公式公表後に追加します。</p>')
    for category,field,label in [('branches','branch','支部'),('terms','ki','養成期')]:
        groups=defaultdict(list)
        for term in terms:
            tmp=defaultdict(list)
            for t,s in term['players'].items():
                if s.get(field):tmp[str(s[field])].append((t,s))
            for key,players in tmp.items():groups[key].append((term,players))
        links=[]
        for i,key in enumerate(sorted(groups,key=lambda x:int(x) if x.isdigit() else x)):
            url=f'{category}-{i}.html';title=key+('期' if field=='ki' else '支部')
            links.append((url,title,f'{len(groups[key])}期分の掲載'))
            body='<p class="sub">各適用期に公式ファイルへ記載された所属・養成期で分類しています。2014年前期以前の住所欄を支部とは扱いません。人数や合計は当該期の掲載分です。</p>'
            for term,ps in reversed(groups[key]):
                n=sum(s['starts'] for _,s in ps);wins=sum(s['wins'] for _,s in ps);top2=sum(s['wins']+s['second'] for _,s in ps)
                rows=[[name(t),e(s['class']),f'{s["win"]:.2f}',f'{s["top2"]:.1f}%<small>{s["starts"]}走</small>'] for t,s in sorted(ps,key=lambda x:-x[1]['win'])]
                body+=f'<details class="panel db-term"><summary><b>{period_label(term)}</b><span>{len(ps)}人 · {n:,}走 · 1着 {rd.rate(wins,n)}</span></summary><p>2連対 {rd.rate(top2,n)} · 優出 {sum(s["finals"] or 0 for _,s in ps)}回 · 優勝 {sum(s["titles"] or 0 for _,s in ps)}回</p>{matrix(["選手","級","公式勝率","2連対"],rows)}</details>'
            put(url,title+'の成績',body)
        put(category+'.html',label+'から探す',cards(links))
    links=[]
    for j,v in sorted(summary.get('venues',{}).items()):
        links.append((f'venue-{j}.html',vn(j),f'{v["n"]:,}レース'))
        rows=[[f'{i}コース',str(n),rd.rate(n,v['n'])] for i,n in enumerate(v['course'],1)]
        pays=[[label,str(n),rd.rate(n,v['payout_n'])] for label,n in zip(('1,000円未満','1,000〜4,990円','5,000〜9,990円','1万〜99,990円','10万円以上'),v['payout_bins'])]
        body=f'<p class="sub">{rd.date(catalog["from"])}〜{rd.date(catalog["through"])}の保存{v["n"]:,}レース。コース不明・同着を含む全レースが分母のため、1着率の合計は100%にならない場合があります。</p>'+rd.section('1着の進入コース',matrix(['コース','1着回数','全レース比'],rows))+rd.section('3連単払戻金の分布',f'<p>平均 {round(v["payout_sum"]/v["payout_n"]):,}円（払戻金が確認できた{v["payout_n"]:,}件）</p>'+matrix(['払戻金','件数','割合'],pays) if v['payout_n'] else '<p>払戻金未収録</p>')+rd.section('勝者の決まり手',matrix(['決まり手','件数','割合'],[[e(k),str(n),rd.rate(n,v['n'])] for k,n in v['kim'].items()]))
        put(f'venue-{j}.html',vn(j)+'の保存結果集計',body)
    put('venues.html','全24場のデータ',cards(links))
    def event_rows(events):
        return [[rd.date(ev['through'])+'<small>'+e(vn(ev['venue']))+' '+str(ev['final']['race'])+'R</small>',e(ev['title'])+'<small>'+e(ev['grade'] or '格付未確認')+'</small>','<br>'.join(name(t) for t in ev['final']['winners'])+'<details><summary>優出選手</summary>'+ '・'.join(name(t) for t in ev['final']['entrants'])+'</details>'] for ev in events if ev['final']]
    events=summary.get('events',[]);years=sorted({ev['through'][:4] for ev in events},reverse=True)
    put('events.html','優勝戦・開催記録','<p class="sub">公式結果のレース名で優勝戦を確認できた開催のみ。格付未確認を一般戦として補完しません。途中までの開催は優勝者を表示しません。</p>'+cards([(f'events-{y}.html',y+'年','優勝者・優出選手') for y in years])+rd.section('直近の確認済み優勝戦',matrix(['日付・場','開催','優勝者'],event_rows([v for v in events if v['final']][:30]))))
    for y in years:put(f'events-{y}.html',y+'年の優勝戦',rd.section('保存結果で確認できた開催',matrix(['日付・場','開催','優勝者'],event_rows([v for v in events if v['through'].startswith(y)]))))
    ranking='<p class="sub">直近90日、当該コース15走以上の選手。小標本の順位は変わりやすく、将来の勝率を示しません。実際に入った進入コースで集計しています。</p>'
    for c in range(1,7):
        rs=sorted((x for x in summary.get('rankings',[]) if x['course']==str(c)),key=lambda x:(-x['places'][0]/x['n'],-x['n']))[:50]
        ranking+=rd.section(f'{c}コースの1着率',matrix(['選手','出走','1着率','平均ST'],[[name(x['player']),str(x['n']),rd.rate(x['places'][0],x['n']),f'{x["st"]:.2f}' if x['st'] is not None else '—'] for x in rs]))
    put('rankings.html','直近90日・コース別ランキング',ranking)
    record='<p class="sub">保存範囲内の記録です。3連単払戻金は100円あたり。舟券の購入実績・予想の回収率とは別の集計です。</p>'
    record+=rd.section('高配当 上位200件',matrix(['日付・場','組番','払戻金'],[[rd.date(r[0])+'<small>'+e(vn(r[1]))+f' {r[2]}R</small>',e(r[3]),f'{r[4]:,}円'] for r in summary.get('high_payout',[])]))
    record+=rd.section('確認できた1着同着',matrix(['日付・場','R','選手'],[[rd.date(r[0])+'<small>'+e(vn(r[1]))+'</small>',str(r[2]),'・'.join(name(t) for t in r[3])] for r in summary.get('ties',[])]))
    record+=rd.section('直近のF・L記録（最大500レース）',matrix(['日付・場','R','記録のある選手'],[[rd.date(r[0])+'<small>'+e(vn(r[1]))+'</small>',str(r[2]),'・'.join(name(t) for t in r[3])] for r in summary.get('accidents',[])]))
    record+=rd.section('3連単の出目',matrix(['組番','出現回数','保存組番内の割合'],[[e(k),str(n),rd.rate(n,sum(summary.get('combinations',{}).values()))] for k,n in sorted(summary.get('combinations',{}).items(),key=lambda x:-x[1])]))
    put('records.html','高配当・同着・スタート事故',record)
    from .race_archive import months
    available=months(site.now.strftime('%Y%m%d'))
    race_payload=json.dumps({'months':available,'venues':{j:vn(j) for j in venues},'names':{t:i['name'] for t,i in roster.items()}},ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    controls='<div class="panel"><div class="rd-filters"><label>月<select id="db-month">'+''.join(f'<option value="{m}">{m[:4]}年{m[4:]}月</option>' for m in available)+'</select></label><label>場<select id="db-venue"><option value="">全24場</option>'+''.join(f'<option value="{j}">{e(vn(j))}</option>' for j in venues)+'</select></label><label>日<select id="db-day"><option value="">月の全日</option>'+''.join(f'<option value="{d:02d}">{d}日</option>' for d in range(1,32))+'</select></label><label>配当<select id="db-payout"><option value="0">すべて</option><option value="10000">万舟以上</option><option value="100000">10万円以上</option></select></label><label>種類<select id="db-type"><option value="">全レース</option><option value="final">優勝戦（レース名確認分）</option><option value="fl">F・Lのあるレース</option><option value="tie">1着同着</option></select></label></div><p id="db-count" class="sub" aria-live="polite">選んだ月の結果を読み込みます。</p></div>'
    race_control='<label>R<select id="db-race"><option value="">全レース</option>'+''.join(f'<option value="{r}">{r}R</option>' for r in range(1,13))+'</select></label>'
    controls=controls.replace('<label>配当',race_control+'<label>配当')
    advanced='<details class="rv-details"><summary>開催・格付・勝ち方で詳しく絞る</summary><div class="rd-filters"><label>開催<select id="db-meeting"><option value="">すべての開催</option></select></label><label>格付<select id="db-grade"><option value="">すべて</option>'+''.join(f'<option value="{g}">{g}</option>' for g in ('SG','PG1','G1','G2','G3'))+'<option value="unknown">未確認</option></select></label><label>勝者の決まり手<select id="db-method"><option value="">すべて</option>'+''.join(f'<option>{k}</option>' for k in rd.KIM)+'</select></label><label>1着の進入コース<select id="db-course"><option value="">すべて</option>'+''.join(f'<option value="{c}">{c}コース</option>' for c in range(1,7))+'</select></label></div><p class="sub">開催・格付は公式ファイルで確認できた分のみ。同じ開催が月をまたぐ場合、この月に保存された結果だけが対象です。</p></details>'
    controls=controls.replace('<p id="db-count"',advanced+'<p id="db-count"')+'<div id="db-analysis" aria-live="polite"></div>'
    put('races.html','全保存レースの結果検索','<p class="sub">日別結果の保存分です。予想の的中実績ではありません。当日分は含めず、月単位で読み込みます。未取得日は非開催と同一視しません。古いSG等の決勝は<a href="championships.html">公式記録集</a>も確認できます。</p>'+controls+'<div id="db-races"></div><div class="rd-pagination"><button type="button" id="db-prev">← 前へ</button><span id="db-page"></span><button type="button" id="db-next">次へ →</button></div><noscript>結果検索はJavaScriptが必要です。選手ページの保存履歴も利用できます。</noscript><script id="db-data" type="application/json">'+race_payload+'</script><script src="../database.js" defer></script>')
    equipment=[];seen=set()
    from .sitegen import DATA, load_json
    day=site.idx.get('date','')
    for p in sorted((DATA/'races'/day).glob('*.json')):
        raw=load_json(p,{}) or {};rl=raw.get('racelist') or {}
        for b in rl.get('boats',[]):
            j=p.stem[:2]
            for kind,prefix in [('モーター','motor'),('ボート','boat')]:
                number=b.get(prefix+'_no');key=(j,kind,number)
                if number is None or key in seen:continue
                seen.add(key);equipment.append([e(vn(j))+'<small>'+kind+str(number)+'</small>',e(b.get(prefix+'_2')),e(b.get(prefix+'_3'))])
    put('equipment.html','ボート・モーターの公式出走表掲載値','<p class="sub">'+rd.date(day)+'の取得済み出走表に掲載された値（%）。当日の出走艇に限ります。交換周期不明の過去の同番号を混ぜて機力とは扱いません。乗り手補正・機歴はモーターページで確認できます。</p>'+rd.section('2連対率・3連対率',matrix(['場・番号','2連対率','3連対率'],equipment)))
    from .championships import ROOT as CHAMPIONSHIPS, records as championship_records
    cats=read_json(CHAMPIONSHIPS/'categories.json.gz',[])
    detailed={(r['category'],r['number']):r for r in championship_records()}
    put('championships.html','SG・PG1・G1公式記録集','<p>公式記録集の歴代優勝者と、取得済みの決勝出走表を掲載します。現在の公式記録集の分類で、当時の格付を推定しません。</p>'+cards([(f'title-{c["id"]}.html',c['name'],c['group']) for c in cats]))
    for cat in cats:
        records=read_json(CHAMPIONSHIPS/'lists'/(cat['id']+'.json.gz'),{}).get('records',[])
        rows=[]
        for r in records:
            detail=detailed.get((r['category'],r['number']))
            winner=' ／ '.join(e(w) for w in r['winners_label'])
            if detail:
                winner=' ／ '.join(name(x['player']) for div in detail['divisions'] for x in div if x['place']=='1') or winner
            if not winner:winner='原記録で確認'
            link=f'champion-{r["category"]}-{r["number"]}.html' if detail else r['source']
            rows.append([rd.date(r['date'])+'<small>'+e(r['venue'])+'</small>',winner,f'<a href="{e(link)}">{e(r["edition"])} 詳細</a>'+('' if detail else '<small>公式ページ</small>')])
            if not detail:continue
            body=f'<p>{e(r["edition"])} · {rd.date(r["date"])} · {e(r["venue"])}</p><p class="sub">記録集区分：{e(r["group"])}。昔の大会は複数のボート種別の決勝があるため、表を分けて保存しています。</p>'
            for i,division in enumerate(detail['divisions'],1):
                result=[]
                for x in division:
                    fields=x['fields'];extra='<details><summary>節間成績・詳細</summary><dl class="db-facts">'+''.join('<div><dt>'+e(k)+'</dt><dd>'+e(v)+'</dd></div>' for k,v in fields.items())+'</dl></details>'
                    result.append([e(x['place']),name(x['player'])+extra,e(fields.get('ST'))+'<small>'+e(fields.get('コース'))+'コース</small>'])
                body+=rd.section('決勝出走表'+(f' {i}' if len(detail['divisions'])>1 else ''),matrix(['着','選手','ST・進入'],result))
            body+=f'<p><a href="{e(r["source"])}">公式の原記録を確認 →</a></p><p class="sub">公式記録にも未記載・調査に基づく項目があります。「-」を0や記録なしに置き換えません。</p>'
            put(f'champion-{r["category"]}-{r["number"]}.html',r['name']+' '+r['edition'],body)
        listing=matrix(['決勝日・場','優勝者','大会'],rows) if records else f'<p>この分類の一覧は取得待ちです。<a href="{e(cat["source"])}">公式の記録集を見る →</a></p>'
        put(f'title-{cat["id"]}.html',cat['name']+' 歴代記録',rd.section('公式記録集の掲載分',listing))
    audit=catalog.get('daily_files',{});pc=read_json(BASE/'period_coverage.json',{})
    coverage=rd.section('現在の保存状況',f'<p>競走結果：{rd.date(catalog["from"])}〜{rd.date(catalog["through"])} · {catalog["races"]:,}レース<br>期別ファイル：公式一覧{pc.get("listed","—")}件中{len(terms)}件保存<br>日別追加取得：{audit.get("saved",0):,}日保存・{audit.get("unavailable",0):,}日未確認<br>集計基準日：{rd.date(catalog["as_of"])}（当日分を除外）</p><p>未確認日は非開催と同一視しません。旧保存履歴と追加Kファイルの重複は日付・場・Rで統合しています。</p>')
    source_days={d:v for path in (BASE/'sources').glob('*.json.gz') for d,v in read_json(path,{}).items()}
    issues=[(d,v) for d,v in sorted(source_days.items(),reverse=True) if v.get('status')!='saved']
    missing=sum(v.get('http_status')==404 for _,v in issues)
    issue_rows=[[rd.date(d),'公式ファイル未発見（404）' if v.get('http_status')==404 else '内容・書式を確認中' if v.get('error')=='ValueError' else '通信等で未取得',f'<a href="{e(v.get("source"))}">公式ファイル</a>'] for d,v in issues[:400]]
    coverage+=rd.section('未確認日の内訳',f'<p>公式ファイル未発見 {missing:,}日 ／ 内容・通信などの未確認 {len(issues)-missing:,}日。</p><details><summary>未確認日を確認（最大400日）</summary>'+matrix(['日付','状況','出典'],issue_rows)+'</details><p class="sub">中止表記だけの日や中身が空のファイルも、出走結果として扱いません。404は公式サイトで取得できなかった意味で、レース非開催の証明ではありません。</p>')
    championship_coverage=read_json(CHAMPIONSHIPS/'coverage.json',{})
    listed_finals=sum(len(read_json(CHAMPIONSHIPS/'lists'/(c['id']+'.json.gz'),{}).get('records',[])) for c in cats)
    coverage+=rd.section('公式大会記録の取得状況',f'<p>分類 {len(cats)}件 · 歴代決勝一覧 {listed_finals:,}大会 · 詳細出走表 {len(detailed):,}大会保存。取得済みの表では登番から選手ページへ結びつけています。</p>')
    coverage+=rd.section('掲載項目と限界',matrix(['項目','状況'],[
        ['選手・公式期別','取得済みの全期・全掲載選手。勝率・連対率・優出・優勝・コース別着順と事故'],
        ['年度・場・コース・枠・展示順位','保存レースを再集計。期間・分母つき。展示順位は6艇分が揃う場合のみ'],
        ['支部・養成期','各公式適用期の掲載値から分類。旧住所を支部に置換しない'],
        ['優勝戦・優出選手','Kファイルの優勝戦表記が確認できた開催。追加取得に合わせ拡大'],
        ['SG・PG1・G1記録','公式記録集の歴代優勝者一覧と取得済み決勝出走表。選手の全出走結果は格付・F/L・優勝戦で検索可能。格付は公式開催名で確認できた分で、予選を含む全出場履歴の全件照合は未完了'],
        ['初出走・初勝利・初優出・初優勝','デビュー以前を含む完全収録の証明がないため生涯初とは表示しない'],
        ['完全優勝・節間最高タイム','開催全日と走破タイムの照合未完了。未掲載'],
        ['モーター・ボート','現行機歴と出走表の公式率を掲載。古い同番号を交換周期を越えて合算しない'],
        ['詳細展示・攻め方','長期データと映像ラベル不足。全攻め試行・ツケマイ・意図の断定はしない']]))
    monthly=[]
    for p in sorted((BASE/'sources').glob('*.json.gz'),reverse=True):
        a=read_json(p,{})
        monthly.append([p.name[:4]+'/'+p.name[4:6],str(sum(v.get('status')=='saved' for v in a.values())),str(sum(v.get('status')!='saved' for v in a.values()))])
    coverage+=rd.section('追加Kファイルの月別取得状況',matrix(['年月','取得日数','未確認日数'],monthly),'従来保存分とは別の追加取得ログです。取得失敗や形式未対応を非開催とは扱いません。毎朝の更新で新しい結果を取り込み、未取得の古い月も順に補完します。')
    coverage+='<p class="sub">旧「艇国データバンク」の全保存データ・独自定義そのものは入手していません。同一性を保証する表示は行わず、公式データで再現できる項目を掲載しています。</p><p><a href="https://www.boatrace.jp/owpc/pc/extra/data/download.html">公式期別成績ダウンロード</a> · <a href="https://www.boatrace.jp/owpc/pc/extra/data/layout.html">公式データ仕様</a> · <a href="https://www1.mbrace.or.jp/od2/K/">公式競走成績ファイル</a></p>'
    put('coverage.html','収録状況・未確認の項目',coverage)
