"""改善項目の再検証。探索の着率と、締切前固定の仮想回収率を分離する。"""
import argparse
from collections import Counter,defaultdict
import gzip
import json
import math
from pathlib import Path

from scraper.exhibition_profile import observations,profiles,baseline,surprise,term_info
from scraper.research_ledger import summarize
from tools.player_research import ROOT,load_records,eligible,strength_key
from tools.exhibition_research import source_races,features,matches,external_candidates
from tools.motor_research import analyze as motor_analyze


def counter():return {'n':0,'win':0,'top3':0}


def completed_source(rows, history_end):
    """日中の未収録日を混ぜず、公式成績履歴の最終日までにそろえる。"""
    return [r for r in rows if r['date']<=history_end]


def add(a,o):
    a['n']+=1;a['win']+=int(o['win']);a['top3']+=int(o['top3'])


def standardized(strata, minimum_controls=5):
    """対象群の構成で比較群を加重。着率差であり因果効果・収益予測ではない。"""
    total_t=sum(v[0]['n'] for v in strata.values());total_c=sum(v[1]['n'] for v in strata.values())
    used_t=used_c=cells=tw=tt=0;cw=ct=variance_sum=0.
    for a,b in strata.values():
        if not a['n'] or b['n']<minimum_controls:continue
        used_t+=a['n'];used_c+=b['n'];cells+=1;tw+=a['win'];tt+=a['top3']
        cw+=a['n']*b['win']/b['n'];ct+=a['n']*b['top3']/b['n']
        pt=a['win']/a['n'];pc=b['win']/b['n']
        variance_sum+=a['n']*pt*(1-pt)+a['n']**2*pc*(1-pc)/b['n']
    diff=(tw-cw)/used_t if used_t else None
    half=1.96*math.sqrt(variance_sum)/used_t if used_t else None
    return {'treatment_n':total_t,'control_n':total_c,'matched_treatment_n':used_t,'matched_control_n':used_c,
            'matched_cells':cells,'treatment_coverage':used_t/total_t if total_t else None,
            'treatment_win_rate':tw/used_t if used_t else None,'control_standardized_win_rate':cw/used_t if used_t else None,
            'win_rate_difference':diff,
            'difference_ci95_independence_approx':[diff-half,diff+half] if used_t else None,
            'treatment_top3_rate':tt/used_t if used_t else None,'control_standardized_top3_rate':ct/used_t if used_t else None,
            'status':'exploratory_association' if used_t else 'insufficient_common_support'}


def personal_comparisons(records, split):
    data=profiles(records);cache={};counts=Counter();monthly=defaultdict(counter)
    cells=defaultdict(lambda:defaultdict(lambda:[counter(),counter()]))
    for r in records:
        if not eligible(r):continue
        obs=observations(r)
        if not obs:continue
        phase='train' if r[0]<split else 'test';term=term_info(r[0])['key'];entries={e[1]:e for e in r[11]}
        for o in obs:
            k=(term,o['toban'])
            if k not in cache:cache[k]=baseline(data,r[0],o['toban'])
            past=cache[k]
            if past['n']<100:continue
            s=surprise(o,past);e=entries[o['toban']]
            stratum=strength_key(r,e)
            if o['solo1']:
                counts['all_solo1']+=1
                name=(phase,o['course'],'rare_vs_other_solo1')
                add(cells[name][stratum][0 if s['rare_baseline'] else 1],o)
                name=(phase,o['course'],'rare_vs_other_solo1_same_player')
                add(cells[name][(o['toban'],r[1])][0 if s['rare_baseline'] else 1],o)
            if s['rare_baseline']:
                name=(phase,o['course'],'solo1_vs_not_solo1_among_rare')
                add(cells[name][stratum][0 if o['solo1'] else 1],o)
            if s['rare_solo1']:
                counts['rare_solo1']+=1;counts['rare_solo1_improved']+=s['rare_solo1_improved']
                add(monthly[(r[0][:6],o['course'])],o)
                name=(phase,o['course'],'improved_vs_not_improved_among_rare_solo1')
                add(cells[name][stratum][0 if s['rare_solo1_improved'] else 1],o)
    comparisons=[];all_cells=[]
    for (phase,c,rule),strata in sorted(cells.items()):
        comparisons.append({'phase':phase,'course':c,'rule':rule,**standardized(strata)})
        all_cells.extend({'phase':phase,'course':c,'rule':rule,'stratum':list(k),'treatment':a,'control':b} for k,(a,b) in sorted(strata.items()))
    return {'counts':dict(counts),'improvement_overlap':counts['rare_solo1_improved']/counts['rare_solo1'] if counts['rare_solo1'] else None,
            'comparisons':comparisons,'strata':all_cells,'monthly':[{'month':m,'course':c,**a} for (m,c),a in sorted(monthly.items())],
            'minimum_controls_per_cell':5,'limits':['比較群の5走以上は固定条件','同じ場・コース・当時級別・全国勝率区分で構成をそろえる',
              '同選手比較は同じ場・コース・選手内で普段1位率の区分が変わった場合のみ','相手選手・気象・機力・進入変化は未補正',
              '後半の結果も確認済みのため、最終的な優位性は未使用期間で検証する']}


def exhibition_dependencies(rows):
    tags=Counter();pairs=Counter();unique=Counter();outer=Counter();details=[]
    for r in rows:
        if not (r.get('result') or {}).get('finished'):continue
        f=features(r)
        if not f:continue
        for c,e in f['course'].items():
            fr=e['frame'];labels=[]
            for rule in (('展示','直線'),('展示','一周'),('一周','まわり足'),('直線','まわり足')):
                if matches(f,fr,rule):labels.append('＋'.join(rule))
            for label in labels:tags[(c,label)]+=1
            for i,a in enumerate(labels):
                for b in labels[i+1:]:pairs[(c,a,b)]+=1
            if labels:unique[c]+=1
        candidates=external_candidates(f)
        if candidates:
            outer['candidate_races']+=1
            for ac,c,label,fr in candidates:
                outer['candidate_rows']+=1
                details.append({'date':r['date'],'jcd':r['jcd'],'rno':r['rno'],'attacker_frame':f['course'][ac]['frame'],
                                'attack_course':ac,'receiver_frame':fr,'receiver_course':c,'rule':label,
                                'label_status':'video_unreviewed','attack_attempt':None,'inside_resistance':None,
                                'attack_type':None,'reviewer':None,'evidence_url':None,'provenance':r.get('provenance'),
                                'video_label_for_prediction':False})
    return {'tags':[{'course':c,'rule':label,'n':n} for (c,label),n in sorted(tags.items())],
            'overlap':[{'course':c,'rule_a':a,'rule_b':b,'n':n} for (c,a,b),n in sorted(pairs.items())],
            'unique_tagged_entries':dict(unique),'outer_candidates':dict(outer),'video_review_queue':details,
            'limits':['重なるタグは独立した加点根拠としない','映像ラベルは事後検証専用。締切前特徴量に混ぜない','勝った決まり手だけで攻めの試行数を代用しない']}


def report(d):
    p=d['personal'];m=d['motors'];l=d['forward_ledger'];a=d['audit']
    lines=['# 改善項目の再検証と考察','',f'元データ：{a["start"]}〜{a["end"]}、{a["source_races"]:,}レース。重複{a["duplicates"]}件。',
           '本番の買い目・予想係数は据え置き。以下は追加の探索と検証記録の改善です。', '',
           '## 本人比の珍しい展示1位は、通常の展示1位より有利か', '',
           '対象＝普段の展示1位率10%以下の選手の単独1位。比較＝それ以外の選手の単独1位。両群とも直前2期100走以上。',
           '場・コース・当時級別・全国勝率の整数区分が同じ比較群が5走以上いる区分だけを使用。対象群の構成へ比較群を加重します。', '',
           '|期間|コース|対象総数|比較可能な対象数|対象1着率|通常の単独1位（構成調整後）|差（ポイント）|参考95%区間（ポイント）|', '|---|---:|---:|---:|---:|---:|---:|---|']
    for row in sorted(p['comparisons'],key=lambda r:(r['phase']=='test',r['course'],r['rule'])):
        if row['rule']!='rare_vs_other_solo1':continue
        pct=lambda v:f'{v:.1%}' if v is not None else '—'
        diff=row['win_rate_difference'];ci=row['difference_ci95_independence_approx']
        ds=f'{diff*100:+.1f}' if diff is not None else '—'
        cs=f'{ci[0]*100:+.1f}〜{ci[1]*100:+.1f}' if ci else '—'
        phase='前半' if row['phase']=='train' else '後半'
        lines.append(f'|{phase}|{row["course"]}|{row["treatment_n"]}|{row["matched_treatment_n"]}|{pct(row["treatment_win_rate"])}|{pct(row["control_standardized_win_rate"])}|{ds}|{cs}|')
    overlap=p['improvement_overlap']
    lines+=['',f'本人比0.03秒改善条件は珍しい単独1位の{overlap:.1%}と重複。独立した材料として二重加点しません。',
            '一般的な展示1位の効果と、本人比の珍しさの追加効果を分離しました。差がプラスでも因果効果・市場を上回る確率・利益を認定しません。',
            '参考95%区間は走の独立を仮定した正規近似。レース・選手の相関や多数条件探索の補正を含まず、確定的な有意差の判定には使いません。',
            '比較できなかった対象も分母に残し、同選手比較・月別件数・全比較区分をJSONに保存。少数区分・同一選手やレースの相関・多数条件探索は残ります。', '',
            '## モーター評価の修正', '',
            '- 成立した6艇・展示6艇が揃うレースに限定。欠測や進入不明を機力の結果基準へ混ぜない。',
            '- 2連対の比較基準も、その日より前の結果だけで更新。同日の結果と未来の成績は使わない。',
            '- モーター自身の走数の途切れではなく、場の開催日と保存された公式開催名の変化で節を区切る。',
            '- 同一場・号機・推定更新期の中で前節と今節を比較。前の乗り手の使用走数と、展示補正の参照走数も保存。',
            '- 直線・一周・まわり足は、該当節の6艇同項目が揃った走だけに接続。別節の値で穴埋めしない。',
            '- 正式な更新日は未取得。推定更新は明示し、伸び型／出足型や本番加点に自動変換しない。',
            '- 観測期間が10日を超える推定節は区切りが不確かとして比較利用不可にする。行を削除せず品質フラグを残す。',
            f'直近比較データ：{len(m["recent_changes"])}件。長すぎる推定節を除いた比較利用可能：{sum(r["comparison_usable"] for r in m["recent_changes"])}件。正式更新日確認済み：0件。', '',
            '## 展示の複合条件・外側展開', '',
            '- 似たタイム条件の重複件数を保存。複数タグの数だけ強いと扱わない。',
            '- 攻め候補と受け手候補を、結果を使わない展示条件で選ぶ。映像確認待ちのレース一覧を保存。',
            '- 映像で攻めの試行・内側の抵抗を確認するまでは、ツケマイ・抵抗・隠す意図を選手の確定特徴にしない。',
            f'外側展開の映像確認待ち：{d["exhibition"]["outer_candidates"].get("candidate_races",0)}レース。', '',
            '## 締切前保存と回収率検証', '',
            '- 出走表・展示・オリジナル展示・オッズ・予想ごとに取得／作成完了時刻を保存。古い値に後付けの時刻を付けない。',
            '- 最後の締切前スナップショットに、その時点の本線＋押さえを各100円とする仮想購入を固定。',
            '- モデル版・展示進入・120通りの予想確率もその時点で固定し、後日の確率校正比較に残す。',
            '- オッズ5分超の古さ、欠けた時刻、予想が展示より古い記録、旧形式は前向き回収率から除外。',
            '- 公式返還艇を含む券は返還。転覆等を自動返還しない。未確認の不成立・結果は未決済として残す。',
            '- 総回収率＝（払戻＋返還）／総購入額。純回収率＝払戻／（総購入額−返還）。実購入成績ではない。',
            '返還の公式説明：https://www.boatrace.jp/owsp/sp/extra/enjoy/guide/jiten/29/y_250.html',
            f'今回の厳密な条件を満たす決済済み記録：{l["races"]}件。0件なら回収率は未算出（null）。', '',
            '## 以前との変更・残る不足', '',
            '|項目|今回の対応|残る条件|','|---|---|---|',
            '|本人比展示|通常の単独1位との構成調整比較、同選手比較、月別内訳|未使用期間での追加効果|',
            '|0.03秒条件|重複率を保存し二重加点を避ける|独立した直線・周回条件の検証|',
            '|モーター|日付順基準、場単位の節区切り、節ごとの複合タイム|正式更新日・開催日程・乗り手未補正の直線等|',
            '|攻めと抵抗|条件候補と映像確認欄を保存|映像による成功・失敗双方のラベル|',
            '|穴の収益性|締切前の入力・オッズ・固定金額・返還を保存し評価|将来の未使用期間の記録|',
            '|本番予想|既存動作と互換性を維持|効果を確認した要因だけ反映する|', '',
            '再実行：`python -m tools.research_review`。固定条件と未検証項目は `improvements.json`、全比較区分は `statistics.json.gz`。', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--split',default='20251001')
    parser.add_argument('--output',type=Path,default=ROOT/'research/improvements');args=parser.parse_args()
    rs,dup=load_records();short=completed_source(source_races(),rs[-1][0])
    d={'audit':{'start':rs[0][0],'end':rs[-1][0],'source_races':len(rs),'duplicates':dup,'split':args.split},
       'personal':personal_comparisons(rs,args.split),'motors':motor_analyze(rs,short),
       'exhibition':exhibition_dependencies(short),'forward_ledger':summarize(short)}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'statistics.json.gz').write_bytes(gzip.compress(json.dumps(d,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    (args.output/'REPORT.md').write_text(report(d),encoding='utf-8')
    print(json.dumps({'audit':d['audit'],'overlap':d['personal']['improvement_overlap'],'motors':len(d['motors']['recent_changes']),
                      'forward_settled':d['forward_ledger']['races']},ensure_ascii=False))


if __name__=='__main__':main()
