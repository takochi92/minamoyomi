# 賞金ページの年末大会装飾

2026-10-27、本人が画像合成を使ったグランプリ・クイーンズの装飾と、おしゃれな金銀銅を要望。

- Built-in image_genでオリジナルの背景2点を生成。公式ロゴ・実際の優勝トロフィー・選手の肖像は使用しない。グランプリは濃紺と金、クイーンズは濃紺／紫と銀・ローズゴールド。
- `site/img/prizes/grand-prix-hero.webp` 115,866 bytes、`queens-hero.webp` 92,916 bytes。1600×533、WebP。元PNGはローカルoutputsに保存。
- 名前・順位・賞金・大会名は画像に焼き込まずHTMLで保持。背景画像は空altの装飾で、読み上げは大会名と現在順位を利用する。
- 金銀銅は既存コードに合わせCSSの金属グラデーションと数字で描画。中央1位、左2位、右3位。順位番号とaria-labelを付け、色だけに依存しない。選手ページへのリンク・絞り込み・賞金差額は維持。
- 画像込みで320／390／1100pxを実Edgeで確認。横切れなし、3名の賞金額が収まること、画像ロード・配置・検索の動作を確認。ローカル証跡outputs/teilog-prize-artwork。

## 生成プロンプト

### Grand Prix
Premium editorial website header background for a Japanese powerboat racing year-end GRAND PRIX ranking page. Landscape 3:1. No words, numbers, logos or watermarks. Midnight navy, brushed champagne gold. Right third: original abstract trophy from sweeping hydroplane hull forms and thin laurel arcs, dark water and restrained turquoise wake. Real-material CGI, luxury motorsport art direction, diagonal light. Left two thirds dark negative space for live HTML text. No faces, official trophy replica, currency or betting slips. Phone-friendly crop.

### Queens Climax
Premium editorial website header background for a Japanese powerboat racing QUEENS CLIMAX ranking page. Landscape 3:1. No text, logos or watermarks. Midnight ink and deep plum; pearlescent silver, rose-gold, pale champagne. Right third: original crown-like racing sculpture of three flowing metallic hydroplane hull contours, silver arches, subtle crystal points above dark water, lavender reflections. Realistic materials, not an official crown replica. Left two thirds very dark negative space for HTML typography. Coordinate with navy-gold Grand Prix but retain an independent silver/rose-gold identity.
