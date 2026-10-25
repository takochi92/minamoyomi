"""Small static landing page; interactive lists are loaded only on this page."""
from html import escape as e
import json


def date(s):
    return f'{s[:4]}/{s[4:6]}/{s[6:]}' if s else '集計待ち'


def render(page, report):
    if not report:
        return '<h1>期末ボーダー・期初F確認</h1><p>公式保存データを集計しています。</p>'
    period = report['period']
    cards = []
    for tier in ('A1', 'A2'):
        b = report['borders'][tier]
        value = f'{b["win"]:.2f}' if b['win'] is not None else '—'
        if b.get('low') is not None and f'{b["low"]:.2f}' != f'{b["high"]:.2f}':
            value = f'{b["low"]:.2f}〜{b["high"]:.2f}'
        prior = f'{b["previous_official"]:.2f}' if b['previous_official'] is not None else '—'
        cards.append(f'<article class="sw-border"><span>{tier}の目安 <small>独自試算</small></span><strong>{value}</strong>'
                     f'<p>前回公式 <b>{prior}</b></p><small>試算枠 {b["quota"]}人 ／ 必要出走 {90 if tier == "A1" else 80}回</small></article>')
    if report['f_preparing']:
        f_title = '次の期初に向けたF確認'
        f_note = f'{date(report["new_start"])}以降の出走表でF0を照合します。今は審査期間中のF記録を確認できます。'
    else:
        f_title = '前期F歴 × 今期の出走表F0'
        f_note = '今期の出走表F0と、前期の本番F記録を照合した確認候補です。'
    quality = f'<p class="sw-warning">対象期間内に公式ファイル未確認の日が{len(report["missing_days"])}日あります。欠落により数値が変わる可能性があります。</p>' if report['missing_days'] else ''
    if report.get('grade_unresolved_races'):
        quality += '<p class="sw-warning">併催などで級区分を確認できないレースがあるため、今期のボーダー試算を見送っています。目標勝率の初期値には前回公式ボーダーを使います。</p>'
    payload = json.dumps(report, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    class_period = report.get('current_class_period')
    class_note = (class_period[:4] + '年' + ('前期' if class_period.endswith('-1') else '後期')) if class_period else '未確認'
    return f'''<h1>期末ボーダー・期初F確認</h1>
<p class="sub">{e(period['label'])}適用分 ／ 審査 {date(period['from'])}〜{date(period['through'])}<br>{date(report['through'])}の結果まで・日次更新</p>
<nav class="sw-links"><a class="btn" href="#border">A1・A2の目安</a><a class="btn" href="#f-check">未消化FL休み</a></nav>
<section class="panel" id="border"><h2>期末の勝率ボーダー <small>公式確定ではありません</small></h2>
<div class="sw-borders">{''.join(cards)}</div>
<p class="sw-warning">勝率だけで昇格・維持は決まりません。出走回数・2連対率30％・3連対率40％・事故率0.70以下などの条件があります。試算は参考名簿{report['roster_n']:,}人の20％枠を使用。期末の登録人数・同率時の扱い・正式な事故点・特殊開催等により変わります。</p>{quality}
<details class="sw-method"><summary>参考値の計算方法・出典</summary><p>公式の保存済み競走成績に、公式年間日程のSG・G1・G2区分と優勝戦加点を合わせて再計算しています。特殊開催・併催の扱いなどで公式勝率と一致しない場合があります。事故点は結果から確認できる分の下限で、不良航法等の点は未収録です。「昇格確定」「降格確定」を示すページではありません。</p>
<p>A1は90走、A2は80走以上を試算条件としています。計算条件が未確認の走は追加加点を0〜4点として2通り計算し、差が出る場合は試算幅を表示します。公式ボーダーを保証する範囲ではありません。目標勝率の初期値は試算の高い側です。目標ラインは変更でき、各選手の現在級と勝率との差を確認できます。表示を見て選手の意図・走り方を断定しないでください。</p>
<p><a href="https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/07/y_047.html" target="_blank" rel="noopener">公式の級別基準</a> ／ <a href="https://www.boatrace.jp/owpc/pc/site/news/2025/04/42234/" target="_blank" rel="noopener">2025年5月からの改正</a> ／ <a href="https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/17/y_164.html" target="_blank" rel="noopener">着順点</a></p></details></section>
<section class="panel sw-browser"><h2>目標ライン付近の選手</h2><p class="sub">現在級：{class_note}の適用級。審査対象期・級の適用期・出走表のF表記の期間は別です。</p>
<div class="sw-controls"><label>見る級<select id="sw-tier"><option>A1</option><option>A2</option></select></label><label>目標勝率<input id="sw-target" type="number" min="0" max="12" step="0.01" value="{report['borders']['A1']['win'] or report['borders']['A1']['previous_official'] or 6.3:.2f}"></label>
<label>絞り込み<select id="sw-scope"><option value="near">ライン±0.30</option><option value="up">上の級を目指す目安</option><option value="keep">現在同級のライン付近</option><option value="below">現在級の目安割れ</option><option value="short">出走回数が不足</option><option value="all">全選手</option></select></label></div>
<input class="sw-search" id="sw-q" type="search" aria-label="選手名・登録番号・支部で検索" placeholder="選手名・登録番号・支部で検索">
<p class="sub">一覧の勝率は参考値です。級別は未確定。数値の下に目標との差を表示します。</p>
<p class="sub" id="sw-count" aria-live="polite"></p><div class="sw-list" id="sw-list"></div><button class="btn" id="sw-more" type="button" hidden>もっと見る</button>
<noscript><p>絞り込み一覧にはJavaScriptが必要です。上のボーダーと出典はそのまま確認できます。</p></noscript></section>
<section class="panel" id="f-check"><h2>未消化FL休み <small>公式に掲載された確認分</small></h2>
<p class="sub">公式出走表の「未消化FL休み」欄を確認。休み期間、掲載時点、出典を選手ごとに表示します。F・Lをまとめた資料のため、すべてを隠れFとは呼びません。</p>
<div class="sw-controls"><label>表示<select id="sw-leave-scope"><option value="active">未消化の記載・掲載日程</option><option value="ended">掲載期間終了・再確認が必要</option><option value="all">保存した確認記録すべて</option></select></label><label>選手をさがす<input id="sw-leave-q" type="search" placeholder="名前・登録番号・支部"></label></div>
<p class="sub" id="sw-leave-count" aria-live="polite"></p><div class="sw-list" id="sw-leave-list"></div>
<details class="sw-method"><summary>確認範囲と「消化済み」の扱い</summary><p>浜名湖の休み日程8件を公式PDFの画像で照合。津は公式の未消化日数欄を毎朝取得します。全国全選手の網羅一覧ではありません。期間が過ぎただけで「消化済み」へ変更せず、「掲載期間終了・再確認なし」とします。欄が空白の選手、未取得の選手も消化済みとは扱いません。津の情報は前検日時点で、開始日・終了日は未掲載。浜名湖は文字を抽出できないため、掲載済み8件以降の追加は画像での確認が必要です。</p></details>
<details class="sw-history"><summary>F履歴・期初F0の照合を見る（消化状況は未確認）</summary><h3>{f_title}</h3><p>{f_note}</p>
<p class="sw-warning">「隠れF」の確定一覧ではありません。前期にFがあっても、F休みを既に消化している場合があります。休みの開始・終了・未消化日数は未照合です。長い出走間隔だけでF休みと判定しません。</p>
<p class="sub">F記録の対象：{date(report['f_period']['from'])}〜{date(report['f_period']['through'])}。出走表F0は、その表の日時時点の表示です。</p>
<div class="sw-controls"><label>表示<select id="sw-f-scope"><option value="recent">期末60日間にF記録</option><option value="f0">今期の出走表F0を確認</option><option value="all">対象期間のF記録すべて</option></select></label><label>選手をさがす<input id="sw-f-q" type="search" placeholder="名前・登録番号・支部"></label></div>
<p class="sub" id="sw-f-count" aria-live="polite"></p><div class="sw-list" id="sw-f-list"></div><button class="btn" id="sw-f-more" type="button" hidden>もっと見る</button></details></section>
<p class="sub"><a href="{page.u('racer/index.html')}">選手・モーター検索へ戻る →</a></p>
<script id="sw-data" type="application/json">{payload}</script><script src="{page.u('season.js')}" defer></script>'''
