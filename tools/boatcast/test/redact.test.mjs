import test from 'node:test';
import assert from 'node:assert/strict';
import { redactUrl, redactText, redactDeep, makeLogger } from '../redact.mjs';

test('URL はドメイン＋パスまで。クエリとハッシュは落とす', () => {
  assert.equal(redactUrl('https://cdn.example.jp/path/seg_1.ts?token=SECRET&x=1#frag'), 'https://cdn.example.jp/path/seg_1.ts');
  assert.equal(redactUrl('https://front.player.boatrace-cdn.jp/player/vod?service=boatcast&stadium=04heiwajima'), 'https://front.player.boatrace-cdn.jp/player/vod');
});

test('認証情報（user:pass@）も落とす', () => {
  assert.equal(redactUrl('https://user:pw@host.example/a/b?q=1'), 'https://host.example/a/b');
});

test('data: / blob: は中身を出さない', () => {
  assert.equal(redactUrl('data:text/html;base64,AAAA'), 'data:[omitted]');
  assert.equal(redactUrl('blob:https://x.example/uuid'), 'blob:[omitted]');
  assert.equal(redactUrl('about:blank'), 'about:blank');
});

test('URL として読めなくても ? から先を落とす', () => {
  assert.equal(redactUrl('//cdn/path?token=abc'), '//cdn/path');
});

test('文章中の URL をすべて伏せる（末尾の句読点は残す）', () => {
  const t = '取得: https://a.example/x/y.m3u8?hdnts=ABC123, 次に https://b.example/z?sig=XYZ.';
  const r = redactText(t);
  assert.ok(!r.includes('ABC123') && !r.includes('XYZ') && !r.includes('?'));
  assert.ok(r.includes('https://a.example/x/y.m3u8,'));
  assert.ok(r.endsWith('https://b.example/z.'));
});

test('Cookie / Authorization / token= を伏せる', () => {
  assert.equal(redactText('Cookie: sid=abc; other=1'), 'Cookie: [REDACTED]');
  assert.equal(redactText('authorization: Bearer abc.def'), 'authorization: [REDACTED]');
  assert.equal(redactText('失敗 token=abc123 でした'), '失敗 token=[REDACTED] でした');
});

test('redactDeep は入れ子の文字列を伏せ、元のオブジェクトは変えない', () => {
  const src = { a: 'https://h.example/p?token=T', b: [{ c: 'https://h2.example/q?sig=S' }], n: 3 };
  const out = redactDeep(src);
  assert.equal(out.a, 'https://h.example/p');
  assert.equal(out.b[0].c, 'https://h2.example/q');
  assert.equal(out.n, 3);
  assert.ok(src.a.includes('token=T'));
});

test('makeLogger はクエリを出力に残さない', () => {
  const lines = [];
  const log = makeLogger('[t]', (s) => lines.push(s));
  log('開く', 'https://h.example/a?token=SECRET', new Error('fail https://h.example/b?sig=SECRET2'), { u: 'https://h.example/c?k=SECRET3' });
  const all = lines.join('\n');
  assert.ok(!/SECRET/.test(all));
  assert.ok(all.includes('https://h.example/a'));
});
