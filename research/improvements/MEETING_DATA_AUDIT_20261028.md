# 節間データ 24場の取得先調査（2026-10-28）

## 結論

- 前検・展示・本番ST・着順は24場すべての直近終了レースで取得・解析を確認。各場1レースの標本確認であり、全開催・全過去レースの欠損ゼロを意味しない。
- 平均展示・平均ST・平均ST順位は公式の平均値を転記するのではなく、上記の公式記録から自サイトで集計する。欠損とF/Lの除外条件は実装・画面の説明に従う。
- 得点率の入口は多数あるが、共通の全国公式pointrankで今回24場のうち表が出たのは尼崎のみ。各場公式へ個別対応が必要。戸田の通常開催を含め24場で継続取得できることは確認できていない。
- 得点率の「ない」は永久に公開されていないという断定ではない。非開催で消えている・特定開催だけ全国公式が出る・開催中でも予選終了時点で固定されるケースを区別する。
- 利用者の「場によって有無が混在する比較列はいらない」に合わせ、得点率・順位・説明・出典リンクを節間比較表から全場共通で外す。既存取得済みメタデータや解析用パーサーは保持。

## 24場の標本検証

前検は登録番号に紐づく有効件数。展示・本番ST・着順は各標本レースの艇数。ST順位は通常STを順位化して平均するため、全場共通で元データがある。

|場|検証日・R|前検人数|展示|本番ST|着順|得点率の場公式調査|
|---|---|---:|---:|---:|---:|---|
|01 桐生|20261027 12R|47|6|6|6|現行表を実取得|
|02 戸田|20261019 12R|48|6|6|6|通常開催の継続取得経路は未確認|
|03 江戸川|20261027 12R|48|6|6|6|現行表を実取得|
|04 平和島|20261027 12R|46|6|6|6|公式入口あり・現在非開催|
|05 多摩川|20261027 12R|46|6|6|6|公式入口あり・現在非開催|
|06 浜名湖|20261026 12R|46|6|6|6|公式入口あり・現在非開催|
|07 蒲郡|20261027 12R|46|6|6|6|公式入口・ヘルプ・得点率項目を確認|
|08 常滑|20261027 12R|45|6|6|6|現行表を実取得|
|09 津|20261027 12R|45|6|6|6|現行表を実取得|
|10 三国|20261028 3R|45|6|6|6|現行表を実取得|
|11 びわこ|20261026 12R|45|6|6|6|公式入口あり・現在非開催|
|12 住之江|20261024 12R|48|6|6|6|公式入口あり・現在非開催|
|13 尼崎|20261027 12R|52|6|6|6|現行表を実取得|
|14 鳴門|20261025 12R|44|6|6|6|公式入口あり・現在非開催|
|15 丸亀|20261027 12R|45|6|6|6|現行表を実取得|
|16 児島|20261027 12R|44|6|6|6|現行表を実取得|
|17 宮島|20261025 12R|43|6|6|6|公式入口あり・現在は表なし|
|18 徳山|20261023 12R|45|6|6|6|公式入口あり・現在非開催|
|19 下関|20261020 11R|45|6|6|6|公式入口あり・現在非開催|
|20 若松|20261025 11R|47|6|6|6|公式入口あり・現在非開催|
|21 芦屋|20261026 12R|45|6|6|6|公式入口あり・現在非開催|
|22 福岡|20261027 12R|47|6|6|6|現行表を実取得|
|23 唐津|20261028 4R|44|6|6|6|現行表を実取得|
|24 大村|20261027 12R|47|6|6|6|10/25指定の予選表を実取得|

## 再確認用の公式URL

全国公式の前検・直前・結果は各場で同じパラメーター構造。以下のリンクは実際に取得して検証した日付・R。

- 桐生：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=01&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=01&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=01&hd=20261027&rno=12)・[場公式の得点率入口](https://www.kiryu-kyotei.com/modules/raceinfo/?page=index_tokuten)
- 戸田：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=02&hd=20261019&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=02&hd=20261019&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=02&hd=20261019&rno=12)・[場公式の得点率入口](https://www.boatrace-toda.jp/race/race_index.html)
- 江戸川：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=03&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=03&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=03&hd=20261027&rno=12)・[場公式の得点率入口](https://www.boatrace-edogawa.com/sp/index.php?page=raceinfo-tokuten)
- 平和島：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=04&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=04&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=04&hd=20261027&rno=12)・[場公式の得点率入口](https://www1.heiwajima.gr.jp/asp/htmlmade/heiwajima/sp/rank/rank.htm)
- 多摩川：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=05&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=05&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=05&hd=20261027&rno=12)・[場公式の得点率入口](https://www.boatrace-tamagawa.com/modules/raceinfo/?page=index_tokutenrank)
- 浜名湖：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=06&hd=20261026&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=06&hd=20261026&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=06&hd=20261026&rno=12)・[場公式の得点率入口](https://www.boatrace-hamanako.jp/modules/raceinfo/?page=index_tokutenrank)
- 蒲郡：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=07&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=07&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=07&hd=20261027&rno=12)・[場公式の得点率入口](https://www.gamagori-kyotei.com/asp/gamagori/kyogi/kyogihtml/index.htm?p=7)
- 常滑：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=08&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=08&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=08&hd=20261027&rno=12)・[場公式の得点率入口](https://www.boatrace-tokoname.jp/sp/index.php?page=raceinfo-tokutenrank)
- 津：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=09&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=09&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=09&hd=20261027&rno=12)・[場公式の得点率入口](https://www.boatrace-tsu.com/sp/index.php?page=raceinfo-tokutenrank)
- 三国：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=10&hd=20261028&rno=3)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=10&hd=20261028&rno=3)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=10&hd=20261028&rno=3)・[場公式の得点率入口](https://www.boatrace-mikuni.jp/modules/raceinfo/?page=index_tokutenrank)
- びわこ：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=11&hd=20261026&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=11&hd=20261026&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=11&hd=20261026&rno=12)・[場公式の得点率入口](https://www.boatrace-biwako.jp/modules/raceinfo/?page=index_tokutenrank)
- 住之江：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=12&hd=20261024&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=12&hd=20261024&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=12&hd=20261024&rno=12)・[場公式の得点率入口](https://www.boatrace-suminoe.jp/asp/htmlmade/suminoe/sp/rank/rank.htm)
- 尼崎：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=13&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=13&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=13&hd=20261027&rno=12)・[場公式の得点率入口](https://www.boatrace-amagasaki.jp/modules/raceinfo/?page=index_tokutenrank)
- 鳴門：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=14&hd=20261025&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=14&hd=20261025&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=14&hd=20261025&rno=12)・[場公式の得点率入口](https://www.n14.jp/modules/raceinfo/?page=index_tokutenrank)
- 丸亀：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=15&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=15&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=15&hd=20261027&rno=12)・[場公式の得点率入口](https://www1.marugameboat.jp/asp/htmlmade/marugame/rank/rank.htm)
- 児島：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=16&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=16&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=16&hd=20261027&rno=12)・[場公式の得点率入口](https://www.kojimaboat.jp/asp/htmlmade/kojima/rank/rank.htm)
- 宮島：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=17&hd=20261025&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=17&hd=20261025&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=17&hd=20261025&rno=12)・[場公式の得点率入口](https://www.boatrace-miyajima.com/yosen_point_rank.html)
- 徳山：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=18&hd=20261023&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=18&hd=20261023&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=18&hd=20261023&rno=12)・[場公式の得点率入口](https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_tokutenrank)
- 下関：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=19&hd=20261020&rno=11)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=19&hd=20261020&rno=11)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=19&hd=20261020&rno=11)・[場公式の得点率入口](https://www.boatrace-shimonoseki.jp/modules/raceinfo/?page=index_tokutenrank)
- 若松：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=20&hd=20261025&rno=11)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=20&hd=20261025&rno=11)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=20&hd=20261025&rno=11)・[場公式の得点率入口](https://www.wmb.jp/modules/raceinfo/?page=index_tokutenrank)
- 芦屋：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=21&hd=20261026&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=21&hd=20261026&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=21&hd=20261026&rno=12)・[場公式の得点率入口](https://www.boatrace-ashiya.com/modules/raceinfo/?page=index_tokutenrank)
- 福岡：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=22&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=22&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=22&hd=20261027&rno=12)・[場公式の得点率入口](https://www.boatrace-fukuoka.com/modules/raceinfo/?page=index_tokuten)
- 唐津：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=23&hd=20261028&rno=4)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=23&hd=20261028&rno=4)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=23&hd=20261028&rno=4)・[場公式の得点率入口](https://www.boatrace-karatsu.jp/sp/index.php?page=raceinfo-tokutenrank)
- 大村：[前検](https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd=24&hd=20261027&rno=12)・[展示](https://www.boatrace.jp/owpc/pc/race/beforeinfo?jcd=24&hd=20261027&rno=12)・[STと着順](https://www.boatrace.jp/owpc/pc/race/raceresult?jcd=24&hd=20261027&rno=12)・[場公式の得点率入口](https://omurakyotei.jp/yosou/point.php?day=20261025)

## 得点率を共通列にしない根拠

- 三国・福岡は現開催中でも予選最終日の固定表を表示。津は最終日前日まで更新との記載。今節の最新成績と同じ時点の指標ではない。
- 蒲郡公式ヘルプは、予選最終日前日までは12R後・予選最終日は毎レースと案内。全場のリアルタイム共通指標として扱えない。
  - https://www.gamagori-kyotei.com/sp/00help/00help.htm
- 戸田は公式トップ・実際の共通ヘッダー・レースインデックス・公開スクリプト・全国公式pointrank・検索結果の得点率早見表示まで確認。特別競走や限定時期の早見は通常開催の常設ランキング取得の裏付けにならない。未確認を非公開と断定しない。
- 現行の取得処理は全国公式＋唐津だけ対応。場公式の入口を見つけたことと、日付/節名/登録番号/更新時点/賞典除外を検証した自動取得の完了は区別する。

## 運用上の範囲

- 通常の5分更新は変更しない。節間の補完は別ワークフローで順次実施。前検・過去展示・ST履歴にも取得前や欠損があり得るので、集計数と—の表示を残す。
- 調査HTML原本・実行ログは作業成果物 outputs/teilog-meeting-audit に保管し、サイトへ公開しない。映像は取得しない。
