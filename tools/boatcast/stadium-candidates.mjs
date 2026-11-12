// 場ごとの stadium 表記の「候補」（未検証の仮説。事実ではない）。
// 平和島が 04heiwajima なので「場コード＋ローマ字」の形を仮定しただけ。この候補をそのまま使うことはない。
// venues.mjs が homesv で1つずつ開き、実際に再生が始まった書き方だけを stadiums.json に記録する。
export const CANDIDATES = {
  '01': ['kiryu', 'kiryuu'], '02': ['toda'], '03': ['edogawa'], '04': ['heiwajima'], '05': ['tamagawa'],
  '06': ['hamanako'], '07': ['gamagori', 'gamagoori'], '08': ['tokoname'], '09': ['tsu', 'tu'], '10': ['mikuni'],
  '11': ['biwako'], '12': ['suminoe'], '13': ['amagasaki'], '14': ['naruto'], '15': ['marugame'],
  '16': ['kojima'], '17': ['miyajima'], '18': ['tokuyama'], '19': ['shimonoseki', 'simonoseki'], '20': ['wakamatsu', 'wakamatu'],
  '21': ['ashiya', 'asiya'], '22': ['fukuoka'], '23': ['karatsu', 'karatu'], '24': ['omura', 'oomura', 'ohmura'],
};

export const candidatesFor = (jo) => (CANDIDATES[jo] || []).map((n) => `${jo}${n}`);
