"""公式サイト(2026-09-25 桐生1R)から採取した HTML 断片でテスト用ページを組み立てる。"""

DEADLINES = """<div class="table1 h-mt10"><table><thead><tr><th colspan="2">レース</th></tr></thead>
<tbody><tr><td class="is-fs14 is-thColor8 is-fBold" colspan="2">締切予定時刻</td>
<td class=" ">15:21</td><td class=" is-activeColor1">15:47</td><td class=" ">16:12</td><td class=" ">16:43</td>
<td class=" ">17:14</td><td class=" ">17:44</td><td class=" ">18:14</td><td class=" ">18:45</td><td class=" ">19:14</td>
<td class=" ">19:41</td><td class=" ">20:08</td><td class=" ">20:35</td></tr></tbody></table></div>"""

RACELIST_BOAT = """<tbody class=" is-fs12"> <tr> <td class="is-boatColor{f} is-fs14" rowspan="4">{fw}</td>
<td rowspan="4"><a href="/owpc/pc/data/racersearch/profile?toban=4872"></a> </td>
<td rowspan="4"> <div class="is-fs11">487{f} / <span class=" ">{cls}</span> </div>
<div class="is-fs18 is-fBold"><a href="/owpc/pc/data/racersearch/profile?toban=4872">山下 流心</a> </div>
<div class="is-fs11">広島/広島 <br>33歳/53.0kg </div> </td>
<td class="is-lineH2" rowspan="4">F{fc} <br>L0 <br>0.18 </td>
<td class="is-lineH2" rowspan="4">{nat} <br>25.84 <br>40.45 </td>
<td class="is-lineH2" rowspan="4">4.11 <br>20.00 <br>34.29 </td>
<td class=" is-lineH2" rowspan="4">3{f} <br>{mot} <br>50.25 </td>
<td class=" is-lineH2" rowspan="4">11 <br>29.38 <br>51.98 </td>
<td rowspan="4">&nbsp;</td> <td class=" is-boatColor5">5</td> </tr>
<tr><td class=" ">5</td></tr><tr><td class=" ">.09</td></tr><tr class="is-fBold"><td class=" "><a href="#">４</a></td></tr> </tbody>"""

FW = "０１２３４５６"


def racelist_html():
    boats = "".join(
        RACELIST_BOAT.format(f=i, fw=FW[i], cls=("A1" if i == 1 else "B1"), fc=(1 if i == 1 else 0),
                             nat=f"{7 - i}.{i}0", mot=f"{30 + i}.00")
        for i in range(1, 7))
    return f"""<main>{DEADLINES}
<div class="heading2_title is-ippan"><h2 class="heading2_titleName">第２０回マンスリーＢＯＡＴＲＡＣＥ杯 男女Ｗ優勝戦</h2></div>
<div class="title16__add2020"><h3 class="title16_titleDetail__add2020"> 一般 1800m </h3><div class="title16_titleLabels__add2020"> </div></div>
<div class="table1"><table><thead><tr><th>枠</th></tr></thead>{boats}</table></div></main>"""


BEFORE_BOAT = """<tbody class="is-fs12 "> <tr> <td class="is-boatColor{f} is-fs14" rowspan="4">{f}</td>
<td rowspan="4"><a href="#"></a></td> <td class="is-fs18 is-fBold" rowspan="4"><a href="#">藤本 元輝</a></td>
<td rowspan="2">52.6kg</td> <td rowspan="4">{ex}</td> <td rowspan="4">{tilt}</td> <td rowspan="4">{prop}</td>
<td class="is-p5-5" rowspan="4"> <ul class="labelGroup1">{parts}</ul> </td> <td>R</td> <td>&nbsp;</td> </tr>
<tr> <td>進入</td> <td>&nbsp;</td> </tr> <tr> <td rowspan="2">{adj}</td> <td>ST</td> <td>&nbsp;</td> </tr>
<tr> <td>着順</td> <td class="is-fBold"><a href="#"></a></td> </tr> </tbody>"""

ST_ROW = """<tr> <td colspan="3"> <div class="table1_boatImage1"> <span class="table1_boatImage1Number is-type{f}">{f}</span>
<span class="table1_boatImage1Line"><span class="table1_boatImage1Boat" style="left: 50%;"></span></span>
<span class="table1_boatImage1Time">{st}</span> </div> </td> </tr>"""

WEATHER = """<div class="weather1"> <p class="weather1_title">水面気象情報 14:55現在</p> <div class="weather1_body">
<div class="weather1_bodyUnit is-direction"> <p class="weather1_bodyUnitImage is-direction14"></p> <div class="weather1_bodyUnitLabel"> <span class="weather1_bodyUnitLabelTitle">気温</span> <span class="weather1_bodyUnitLabelData">24.0℃</span> </div> </div>
<div class="weather1_bodyUnit is-weather"> <p class="weather1_bodyUnitImage is-weather2"></p> <div class="weather1_bodyUnitLabel"> <span class="weather1_bodyUnitLabelTitle">曇り</span> </div> </div>
<div class="weather1_bodyUnit is-wind"> <div class="weather1_bodyUnitLabel"> <span class="weather1_bodyUnitLabelTitle">風速</span> <span class="weather1_bodyUnitLabelData">4m</span> </div> </div>
<div class="weather1_bodyUnit is-windDirection"> <p class="weather1_bodyUnitImage is-wind10"></p> </div>
<div class="weather1_bodyUnit is-waterTemperature"> <div class="weather1_bodyUnitLabel"> <span class="weather1_bodyUnitLabelTitle">水温</span> <span class="weather1_bodyUnitLabelData">23.0℃</span> </div> </div>
<div class="weather1_bodyUnit is-wave"> <div class="weather1_bodyUnitLabel"> <span class="weather1_bodyUnitLabelTitle">波高</span> <span class="weather1_bodyUnitLabelData">3cm</span> </div> </div>
</div> <div class="weather1_stand">スタンド</div> </div>"""

# 実データ：展示タイム・チルト、スタート展示の並び(1,2,3,5,6,4)と ST
REAL_EX = {1: ("6.83", "-0.5"), 2: ("6.71", "0.0"), 3: ("6.88", "-0.5"), 4: ("6.89", "-0.5"), 5: ("6.66", "-0.5"), 6: ("6.81", "-0.5")}
REAL_ST = [(1, "F.08"), (2, ".16"), (3, ".13"), (5, ".34"), (6, ".06"), (4, ".05")]


def beforeinfo_html(exhibited=True):
    boats = "".join(
        BEFORE_BOAT.format(f=f, ex=(REAL_EX[f][0] if exhibited else "&nbsp;"), tilt=REAL_EX[f][1],
                           prop=("新" if f == 3 else "&nbsp;"),
                           parts=('<li><span class="label4 is-type1">ピストン</span></li>' if f == 6 else " "),
                           adj=("1.0" if f == 4 else "0.0"))
        for f in range(1, 7))
    st = "".join(ST_ROW.format(f=f, st=s) for f, s in REAL_ST) if exhibited else ""
    return f"""<main>{DEADLINES}<div class="table1"><table class="is-w748"><thead><tr><th>枠</th></tr></thead>{boats}</table></div>
<div class="table1"><table class="is-w238"><thead><tr><th colspan="3">スタート展示</th></tr></thead><tbody class="is-p10-0">{st}</tbody></table></div>
{WEATHER}</main>"""


RESULT = """<main><div class="table1"><table class="is-w495"><thead><tr><th>勝式</th><th>組番</th><th>払戻金</th><th>人気</th></tr></thead>
<tbody> <tr class="is-p3-0"> <td rowspan="2">3連単</td> <td> <div class="numberSet1 is-small"> <div class="numberSet1_row">
<span class="numberSet1_number is-type1">1</span><span class="numberSet1_text">-</span><span class="numberSet1_number is-type5">5</span><span class="numberSet1_text">-</span><span class="numberSet1_number is-type4">4</span>
</div> </div> </td> <td><span class="is-payout1">¥5,060</span></td> <td>16</td> </tr> </tbody>
<tbody> <tr class="is-p3-0"> <td>単勝</td> <td> <div class="numberSet1 is-small"> <div class="numberSet1_row">
<span class="numberSet1_number is-type1">1</span></div> </div> </td> <td><span class="is-payout1">¥150</span></td> <td></td> </tr> </tbody>
<tbody> <tr class="is-p3-0"> <td rowspan="2">2連単</td> <td> <div class="numberSet1 is-small"> <div class="numberSet1_row">
<span class="numberSet1_number is-type1">1</span><span class="numberSet1_text">-</span><span class="numberSet1_number is-type5">5</span>
</div> </div> </td> <td><span class="is-payout1">¥1,230</span></td> <td>5</td> </tr> </tbody></table></div>
<div class="table1"><table class="is-w243 is-h108__3rdadd"><thead><tr><th>決まり手</th></tr></thead><tbody><tr><td>逃げ</td></tr></tbody></table></div></main>"""

INDEX = """<main><div class="table1"><table><thead><tr><th>ボートレース場</th></tr></thead>
<tbody><tr><td class="is-arrow1" rowspan="2"><a href="#">桐生</a></td><td rowspan="2">2R以降<br>発売中</td><td>2R</td>
<td rowspan="2" class="is-ippan "></td><td rowspan="2" class="is-nighter"></td>
<td class="is-alignL" rowspan="2"><a href="/owpc/pc/race/raceindex?jcd=01&amp;hd=20260925">第２０回マンスリーＢＯＡＴＲＡＣＥ杯　男女Ｗ優勝戦</a></td>
<td rowspan="2">9/20-9/25<br>最終日</td></tr><tr><td>15:47</td></tr></tbody>
<tbody><tr><td class="is-arrow1" rowspan="2"><a href="#">びわこ</a></td><td rowspan="2">11R以降</td><td>11R</td>
<td rowspan="2" class="is-G3 "></td><td rowspan="2" class=""></td>
<td class="is-alignL" rowspan="2"><a href="/owpc/pc/race/raceindex?jcd=11&amp;hd=20260925">つるやパン提供 第11回みんなの</a></td>
<td rowspan="2">9/22-9/27<br>4日目</td></tr><tr><td>15:40</td></tr></tbody></table></div></main>"""
