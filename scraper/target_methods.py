"""Static, accessible winning-method bars using the score's exact sample."""
from html import escape
from math import isfinite

# Positions in overperf.course_methods: starts, wins, six KIM counts, unknown.
GROUPS = [('sashi', '差し', (3,)), ('makuri', 'まくり', (4,)),
          ('makuzashi', 'まくり差し', (5,)), ('other', 'その他', (2, 6, 7)),
          ('unknown', '決まり手未確認', (8,))]


def render(record, starts, wins):
    if not record or len(record) != 9:
        return '<p class="tm-missing">同じ集計条件の決まり手は確認中です。</p>'
    if any(not isinstance(x, (int, float)) or not isfinite(x) or x < 0 or int(x) != x for x in record):
        return '<p class="tm-missing">決まり手の集計を再確認しています。</p>'
    if record[0] != starts or record[1] != wins or sum(record[2:]) != wins or wins > starts or starts <= 0:
        return '<p class="tm-missing">決まり手の集計条件を再確認しています。</p>'
    values = [(key, label, sum(record[i] for i in indices)) for key, label, indices in GROUPS]
    values.append(('rest', '1着以外', starts-wins))
    segments, captions = [], []
    for key, label, n in values:
        if not n:
            continue
        segments.append(f'<span class="tm-seg tm-{key}" style="width:{n/starts*100:.6f}%" aria-hidden="true"></span>')
        if key != 'rest':
            captions.append(f'<span><i class="tm-swatch tm-{key}" aria-hidden="true"></i>{label} <b>{n}回</b> <small>{n/starts*100:.1f}%</small></span>')
    label = f'対象{starts}走中、' + '、'.join(f'{name}{n}回' for _, name, n in values if n)
    return (f'<div class="tm-track" role="img" aria-label="{escape(label, quote=True)}" data-starts="{starts}" data-wins="{wins}">'
            + ''.join(segments) + '</div><div class="tm-counts">' + ''.join(captions)
            + f'</div><div class="tm-basis">対象{starts}走を100％（1着以外{starts-wins}走を含む）</div>')


def legend():
    return '<div class="tm-legend">' + ''.join(
        f'<span><i class="tm-swatch tm-{key}" aria-hidden="true"></i>{label}</span>'
        for key, label in [('sashi','差し'), ('makuri','まくり'), ('makuzashi','まくり差し'),
                           ('other','その他'), ('unknown','未確認'), ('rest','1着以外')]) + '</div>'
