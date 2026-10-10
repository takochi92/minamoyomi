"""保存済み1着スコアを順に追加した説明。因果効果や独立加点ではない。"""
import math

GROUPS = [
    ('選手・コース', {'選手のコース別成績','選手のコース別連対','インでの成績','全国勝率','当地勝率','級別','選手のこの場の得意・苦手','選手のこの場でのイン'}),
    ('機力', {'モーター','ボート','乗り手補正の機力展示'}),
    ('展示', {'展示タイム','本人の通常展示との差','本人比の珍しい展示1位','展示のいつもとの差','展示で壁より速い'}),
    ('スタート', {'平均ST','F持ち','壁よりスタートが早い','壁がF持ち'}),
    ('展開・水面', set()),
]


def soft(scores):
    vals = [math.exp(x-max(scores)) for x in scores]
    return [v/sum(vals) for v in vals]


def explain(boats):
    if len(boats) != 6 or any(not b.get('parts') for b in boats):
        return {}
    baseline = {'場のコース別1着率','base_2','base_3'}
    used = baseline | set().union(*(names for _, names in GROUPS))
    scores = [sum(v for k,v in b['parts'].items() if k in baseline) for b in boats]
    prev = soft(scores)
    out = {str(b['frame']): {'baseline':prev[i], 'changes':[]} for i,b in enumerate(boats)}
    for label,names in GROUPS:
        for i,b in enumerate(boats):
            scores[i] += sum(v for k,v in b['parts'].items() if k in names or (not names and k not in used))
        current = soft(scores)
        for i,b in enumerate(boats):
            out[str(b['frame'])]['changes'].append({'label':label,'delta':current[i]-prev[i]})
            out[str(b['frame'])]['final'] = current[i]
        prev = current
    return out
