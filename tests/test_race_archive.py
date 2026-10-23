import gzip,json
from scraper import race_archive as archive


def test_month_merge_keeps_partial_legacy_days_and_prefers_rich_rows(tmp_path):
    old=tmp_path/'history';new=tmp_path/'archive';old.mkdir();new.mkdir()
    r=['20261022','01',1,'逃げ','北',2,0,0,'1-2-3',1200,1,[]]
    r2=[*r];r2[0]='20261023'
    future=[*r];future[0]='20261024'
    cancelled=[*r];cancelled[2]=2
    rich=r+[{'title':'公式開催'}]
    for folder,rows in ((old,[r,r2,future,cancelled]),(new,[rich])):
        (folder/'202610.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(x) for x in rows)+'\n').encode()))
    rows=archive.month_records('202610','20261024',old,new)
    assert len(rows)==2 and len(rows[1])==13 and rows[0][0]=='20261023'
    assert archive.months('20260930',old,new)==[]
    assert archive.months('20261024',old,new)==['202610']
