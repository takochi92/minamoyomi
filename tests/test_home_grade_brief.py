from scraper.sitegen import Page,Site


def test_all_official_grade_icons_and_unique_venue_links():
    s=Site.__new__(Site)
    s.idx={'venues':[{'jcd':f'{i:02}','name':'確認用会場','grade':g,'title':'長いレース名称を省略せず持つテスト'}
                     for i,g in enumerate(('SG','PG1','G1','G2','G3'),1)]}
    html=s.grade_banner(Page('index.html'))
    for i,g in enumerate(('SG','PG1','G1','G2','G3'),1):
        assert f'img/grades/{g.lower()}.png' in html
        assert f'alt="{g}"' in html and f'#grade-{i:02}' in html
    assert html.count('class="grade-brief-row"')==5
    assert '<h2' not in html and 'class="panel"' not in html
    assert '長いレース名称を省略せず持つテスト' in html
    for v in s.idx['venues']:v['cancelled']=True
    assert s.grade_banner(Page('index.html'))==''
