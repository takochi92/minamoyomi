import pytest
from scraper import fl_leave as fl
from scraper.database_sources import write_json


def table():
    # Real two-column layout can flatten without a newline before the next class.
    return 'F・L休み 未消化 ※Ｆ・Ｌ休み未消化 … 前検日時点\n' + ''.join(
        f'A1 {4000+i} 確 認 選 手 滋賀 6.41'+(' 30日 ' if i == 2 else ' ')
        for i in range(45))


def test_official_table_joins_columns_without_inventing_leave_for_blank_cells():
    rows = fl.parse_tsu(table())
    assert len(rows) == 45
    assert [r['toban'] for r in rows if r['days']] == ['4002']
    assert rows[2]['name'] == '確認選手' and rows[2]['days'] == 30
    assert rows[0]['days'] is None


@pytest.mark.parametrize('text', ['選手成績 A1 4002 確認 選手 滋賀 6.41 30日',
                                  'F・L休み 未消化 前検日時点 A1 4002 確認 選手 滋賀 6.41 30日'])
def test_wrong_or_incomplete_pdf_is_not_a_valid_zero_unserved_list(text):
    with pytest.raises(ValueError):
        fl.parse_tsu(text)


def document(**record):
    return dict(venue='公式場', source='https://www.boatrace-tsu.com/official.pdf',
                sha256='a'*64, checked_at='2026-10-25T18:00:00+09:00', document_date='20261026',
                basis='前検日時点', records=[dict(toban='4002', name='確認選手', days=30, **record)])


@pytest.mark.parametrize('day,status', [('20261025','scheduled'),('20261101','in_period'),
                                       ('20261130','in_period'),('20261201','ended_unverified')])
def test_planned_period_is_never_promoted_to_actual_consumption(tmp_path, monkeypatch, day, status):
    monkeypatch.setattr(fl, 'STORE', tmp_path)
    write_json(tmp_path/'official.json', document(start='20261101', end='20261130'))
    out = fl.published_records(day)['records']
    assert out[0]['status'] == status
    assert 'consumed' not in status


def test_snapshot_expires_and_future_checks_cannot_be_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, 'STORE', tmp_path)
    write_json(tmp_path/'official.json', document(start=None, end=None))
    assert not fl.published_records('20261024')['records']
    assert fl.published_records('20261025')['records'][0]['status'] == 'snapshot_unserved'
    assert fl.published_records('20261102')['records'][0]['status'] == 'stale_unverified'


def test_fetch_error_preserves_last_verified_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, 'STORE', tmp_path)
    old=document(start=None, end=None)
    write_json(tmp_path/'tsu.json',old)
    monkeypatch.setattr(fl,'fetch',lambda *a: (_ for _ in ()).throw(RuntimeError('offline')))
    with pytest.raises(RuntimeError):
        fl.refresh_tsu()
    assert fl.read_json(tmp_path/'tsu.json') == old
