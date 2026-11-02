from copy import deepcopy
from bs4 import BeautifulSoup
from scraper.parts_view import block


def race():
    return {'date': '20261102', 'jcd': '06', 'rno': 1,
            'before': {'boats': [{'frame': frame, 'name': f'選手{frame}', 'parts': [], 'propeller': ''}
                                 for frame in range(1, 7)]}}


def badge(frame):
    return f'<b class="boat">{frame}</b>'


def test_empty_official_fields_are_distinct_from_unavailable_old_records():
    confirmed = BeautifulSoup(block(race(), badge), 'html.parser')
    assert confirmed.get_text() == '部品交換記載なし'
    assert not confirmed.select('details')
    for data in ({}, {'before': {'boats': []}}, {'before': {'boats': [{'frame': 1}]}}):
        assert BeautifulSoup(block(data, badge), 'html.parser').get_text() == '部品交換未取得'
    old = race()
    del old['before']['boats'][2]['parts']
    assert '未取得' in block(old, badge) and '記載なし' not in block(old, badge)


def test_partial_data_keeps_known_parts_and_marks_remaining_fields_unknown():
    data = race()
    data['before']['boats'][3]['parts'] = ['ピストン×2', 'リング×4']
    del data['before']['boats'][0]['propeller']
    data['before']['boats'][4]['parts'] = None
    doc = BeautifulSoup(block(data, badge), 'html.parser')
    assert doc.summary.get_text() == '部品交換1艇・一部未取得'
    assert doc.select_one('.parts-tiny-row').get_text() == '4ピストン×2／リング×4'
    assert not doc.details.has_attr('open')
    assert '選手4' not in doc.get_text()


def test_full_six_boats_and_new_propeller_are_escaped_without_mutating_input():
    data = race()
    for boat in data['before']['boats']:
        boat.update(parts=['ピストン×2', 'リング×4', '電気', 'キャブ', 'シリンダ', 'シャフト', 'ギヤ', 'キャリボ'])
    data['before']['boats'][1]['propeller'] = '新'
    data['before']['boats'][2]['parts'].append('<img src=x onerror=alert(1)>')
    before = deepcopy(data)
    doc = BeautifulSoup(block(data, badge), 'html.parser')
    assert doc.summary.get_text() == '部品交換6艇'
    assert len(doc.select('.parts-tiny-row')) == 6
    assert len(doc.select('.boat')) == 6
    assert '新ペラ' in doc.get_text()
    assert not doc.select('img,script')
    assert '<img src=x onerror=alert(1)>' in doc.get_text()
    assert doc.select_one('[role="region"]')['tabindex'] == '0'
    assert '節間の累積履歴ではありません' in doc.get_text()
    assert data == before


def test_new_propeller_only_and_safe_source_identity():
    data = race()
    data['before']['boats'][0]['propeller'] = '新'
    doc = BeautifulSoup(block(data, badge), 'html.parser')
    assert doc.select_one('.parts-tiny-row').get_text() == '1新ペラ'
    assert doc.a['href'] == 'https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20261102&jcd=06&rno=1'
    for key, value in [('date', '"><script>'), ('jcd', '25'), ('rno', True), ('rno', 13)]:
        invalid = deepcopy(data)
        invalid[key] = value
        assert not BeautifulSoup(block(invalid, badge), 'html.parser').select('a')
