import json
from scraper.sitegen import Site


def test_cancelled_venues_and_races_are_not_notified():
    s=Site.__new__(Site)
    s.idx={'date':'20261027','venues':[
        {'jcd':'01','cancelled':True,'races':[{'rno':1,'deadline':'12:00'}]},
        {'jcd':'03','races':[{'rno':1,'deadline':'12:00','cancelled':True},{'rno':2,'deadline':'13:00'}]}]}
    files={};s.put=lambda p,v:files.__setitem__(p,v)
    s.fav_today({'1234':[('20261027','01',1,1),('20261027','03',1,4),('20261027','03',2,6)]})
    rows=json.loads(files['fav-today.json'])['racers']['1234']
    assert len(rows)==1 and rows[0][1]==2 and rows[0][4]==6
