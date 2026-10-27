"""Small static landing page; interactive lists are loaded only on this page."""
from html import escape as e
import json


def date(s):
    return f'{s[:4]}/{s[4:6]}/{s[6:]}' if s else '集計待ち'


def render(page, report):
    if not report:
        return '<h1>期末A1・A2ボーダー</h1><p>公式保存データを集計しています。</p>'
    period = report['period']
    cards = []
    for tier in ('A1', 'A2'):
        b = report['borders'][tier]
        value = f'{b["win"]:.2f}' if b['win'] is not None else '—'
        if b.get('low') is not None and f'{b["low"]:.2f}' != f'{b["high"]:.2f}':
            value = f'{b["low"]:.2f}〜{b["high"]:.2f}'
        prior = f'{b["previous_official"]:.2f}' if b['previous_official'] is not None else '—'
        if b['win'] is None:value=prior
        cards.append(f'<article class="sw-border"><span>{tier} 目標勝率 <small>{"参考目安" if b["win"] is not None else "前回公式を使用"}</small></span><strong>{value}</strong>'
                     f'<small>出走条件 {90 if tier == "A1" else 80}走</small></article>')
    quality = f'<p class="sw-warning">対象期間内に公式ファイル未確認の日が{len(report["missing_days"])}日あります。欠落により数値が変わる可能性があります。</p>' if report['missing_days'] else ''
    if report.get('grade_unresolved_races'):
        quality += '<p class="sw-warning">併催などで級区分を確認できないレースがあるため、今期のボーダー試算を見送っています。目標勝率の初期値には前回公式ボーダーを使います。</p>'
    public = {k: v for k, v in report.items() if k not in {'f_period', 'f_preparing', 'new_start', 'f_players', 'fl_leave'}}
    public['players'] = [{k: v for k, v in p.items() if k != 'f'} for p in report['players']]
    payload = json.dumps(public, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    class_period = report.get('current_class_period')
    class_note = (class_period[:4] + '年' + ('前期' if class_period.endswith('-1') else '後期')) if class_period else '未確認'
    return f'''<h1>期末A1・A2ボーダー</h1>
<p class="sub">審査期限 {date(period['through'])} ／ {date(report['through'])}の結果まで</p>

<section class="sw-overview" id="border"><h2>目標勝率 <small>公式確定ではありません</small></h2>
<div class="sw-borders">{''.join(cards)}</div>
<details class="sw-method"><summary>条件・計算方法・出典</summary><p class="sw-warning">勝率だけで昇格・維持は決まりません。出走回数・2連対率30％・3連対率40％・事故率0.70以下などの条件があります。試算は参考名簿{report['roster_n']:,}人の20％枠を使用。期末の登録人数・同率時の扱い・正式な事故点・特殊開催等により変わります。</p>{quality}<p>公式の保存済み競走成績に、公式年間日程のSG・G1・G2区分と優勝戦加点を合わせて再計算しています。特殊開催・併催の扱いなどで公式勝率と一致しない場合があります。事故点は結果から確認できる分の下限で、不良航法等の点は未収録です。「昇格確定」「降格確定」を示すページではありません。</p>
<p>A1は90走、A2は80走以上を試算条件としています。計算条件が未確認の走は追加加点を0〜4点として2通り計算し、差が出る場合は試算幅を表示します。公式ボーダーを保証する範囲ではありません。目標勝率の初期値は試算の高い側です。目標ラインは変更でき、各選手の現在級と勝率との差を確認できます。表示を見て選手の意図・走り方を断定しないでください。</p>
<p><a href="https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/07/y_047.html" target="_blank" rel="noopener">公式の級別基準</a> ／ <a href="https://www.boatrace.jp/owpc/pc/site/news/2025/04/42234/" target="_blank" rel="noopener">2025年5月からの改正</a> ／ <a href="https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/17/y_164.html" target="_blank" rel="noopener">着順点</a></p></details></section>
<section class="panel sw-browser"><h2>あと何走・何着が必要？</h2>
<div class="sw-controls"><label>見る級<select id="sw-tier"><option>A1</option><option>A2</option></select></label><label>目標勝率<input id="sw-target" type="number" min="0" max="12" step="0.01" value="{report['borders']['A1']['win'] or report['borders']['A1']['previous_official'] or 6.3:.2f}"></label>
</div><details class="sw-method" id="sw-advanced"><summary>絞り込み・並び順</summary><div class="sw-controls"><label>絞り込み<select id="sw-scope"><option value="near">ライン±0.30</option><option value="up">上の級を目指す目安</option><option value="keep">現在同級のライン付近</option><option value="below">現在級の目安割れ</option><option value="short">出走回数が不足</option><option value="all">全選手</option></select></label><label>並び順<select id="sw-sort"><option value="desc">勝率の高い順</option><option value="asc">勝率の低い順</option><option value="near">目標に近い順</option></select></label></div></details>
<input class="sw-search" id="sw-q" type="search" aria-label="選手名・登録番号・支部で検索" placeholder="選手名・登録番号・支部で検索">
<div class="sw-condition-controls"><label>残り出走<select id="sw-mode"><option value="auto">本日の確認済み出走</option><option value="scenario">残り走数を指定（仮定）</option></select></label>
<div id="sw-scenario" hidden><label>残り走数（仮定）<input id="sw-remaining" type="number" min="1" max="12" step="1" value="2"></label>
<label>競走（仮定）<select id="sw-kind"><option value="general">一般・G3</option><option value="graded">G1・G2</option><option value="sg">SG</option></select></label>
<label class="sw-final"><input id="sw-final" type="checkbox">最後の１走は優勝戦と仮定</label></div></div>
<details class="sw-method"><summary>必要点の計算について</summary><p>現在級：{class_note}の適用級。審査対象期と級の適用期は別です。</p><p>「あと何着」は設定した目標勝率に対する参考条件です。本日以降の出走は決めつけず、期末当日以外は本日の残りと期末全体を区別します。仮定モードでは残り走数・競走を自分で指定できます。</p><p>必要点＝目標勝率×（現在の出走数＋残り走数）−現在の着順点合計を、整数の点まで切り上げます。丸め前の勝率が目標以上となる条件で、公式発表の端数処理や級別の確定判定ではありません。SG・G1・G2・優勝戦の着順点、出走回数・連対率・確認できた事故点の条件も合わせて確認します。今後は事故・欠場・同着なしを仮定し、不良航法など未収録の事故点と動く全国ボーダーは別に確認が必要です。</p></details>
<p class="sub" id="sw-count" aria-live="polite"></p><div class="sw-list" id="sw-list"></div><button class="btn" id="sw-more" type="button" hidden>もっと見る</button>
<noscript><p>絞り込み一覧にはJavaScriptが必要です。上のボーダーと出典はそのまま確認できます。</p></noscript></section>
<p class="sub"><a href="{page.u('racer/index.html')}">選手・モーター検索へ戻る →</a></p>
<script id="sw-data" type="application/json">{payload}</script><script src="{page.asset('season.js')}" defer></script>'''
