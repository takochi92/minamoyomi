import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPlayerUrl, resolveVenue, isValidDate, venuePageUrl, STADIUMS, UrlBuildError } from '../player-url.mjs';

test('平和島12R展示（検証済みの形）と完全に一致する', () => {
  assert.equal(
    buildPlayerUrl({ date: '20261112', venue: '04', race: 12 }),
    'https://front.player.boatrace-cdn.jp/player/vod?service=boatcast&stadium=04heiwajima&raceType=exhibition&raceDate=20261112&raceNumber=12&autoplay=0&bitrate=low',
  );
});

test('場は場コード・場名・slug のどれでも平和島になる', () => {
  for (const v of ['04', 4, '平和島', 'heiwajima', '04heiwajima']) assert.equal(resolveVenue(v).slug, '04heiwajima');
});

test('平和島以外は未検証なので例外（推測で組み立てない）', () => {
  for (const jo of Object.keys(STADIUMS).filter((k) => k !== '04')) {
    assert.equal(STADIUMS[jo].slug, null, `${jo} は slug 空欄のまま`);
    assert.throws(() => buildPlayerUrl({ date: '20261112', venue: jo, race: 1 }), UrlBuildError);
  }
});

test('raceType は exhibition だけ、bitrate は low だけ', () => {
  assert.throws(() => buildPlayerUrl({ date: '20261112', race: 12, raceType: 'race' }), /未検証/);
  assert.throws(() => buildPlayerUrl({ date: '20261112', race: 12, bitrate: 'high' }), /未検証/);
});

test('日付とレース番号の検証', () => {
  assert.ok(isValidDate('20260229') === false);
  assert.ok(isValidDate('20240229'));
  assert.throws(() => buildPlayerUrl({ date: '2026-11-12', race: 12 }), UrlBuildError);
  assert.throws(() => buildPlayerUrl({ date: '20261112', race: 0 }), UrlBuildError);
  assert.throws(() => buildPlayerUrl({ date: '20261112', race: 13 }), UrlBuildError);
  assert.throws(() => buildPlayerUrl({ date: '20261112', race: 1.5 }), UrlBuildError);
});

test('1桁のレース番号は既定では「1」。padRace で「01」（未検証の切り分け用）', () => {
  assert.ok(buildPlayerUrl({ date: '20261112', race: 1 }).includes('raceNumber=1&'));
  assert.ok(buildPlayerUrl({ date: '20261112', race: 1, padRace: true }).includes('raceNumber=01&'));
});

test('場ページのURL', () => {
  assert.equal(venuePageUrl('04'), 'https://race.boatcast.jp/?jo=04');
});
