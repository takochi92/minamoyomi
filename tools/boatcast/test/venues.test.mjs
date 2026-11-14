import test from 'node:test';
import assert from 'node:assert/strict';
import { candidateOrder, mergeResults } from '../venues.mjs';
import { candidatesFor, CANDIDATES } from '../stadium-candidates.mjs';

test('候補は24場ぶんあり、場コードで始まる', () => {
  assert.equal(Object.keys(CANDIDATES).length, 24);
  assert.ok(candidatesFor('04').includes('04heiwajima'));
  for (const jo of Object.keys(CANDIDATES)) assert.ok(candidatesFor(jo).every((s) => s.startsWith(jo)));
});

test('試す順番：場ページの値 → 記録済み → 候補。他場の値や変な値は捨てる', () => {
  const o = candidateOrder('01', { fromPage: ['01frompage', '02other', 'bad?x'], recorded: '01recorded' });
  assert.deepEqual(o.slice(0, 2), [{ slug: '01frompage', source: 'venue-page' }, { slug: '01recorded', source: 'recorded' }]);
  assert.ok(o.some((x) => x.source === 'candidate'));
  assert.ok(!o.some((x) => x.slug.startsWith('02')));
  assert.equal(candidateOrder('04')[0].source, 'builtin');
});

test('記録：再生できた場だけ書く。失敗しても、前の確認済みは消さない', () => {
  const before = { '01': { slug: '01old', evidence: 'pr-tool-homesv' } };
  const m = mergeResults(before, [
    { jo: '01', confirmed: null },
    { jo: '02', confirmed: { slug: '02x', source: 'candidate', duration: 300 } },
    { jo: '03', confirmed: null },
  ], { date: '20261112', race: 1, now: 'T' });
  assert.equal(m['01'].slug, '01old');
  assert.deepEqual([m['02'].slug, m['02'].evidence, m['02'].source, m['02'].name], ['02x', 'pr-tool-homesv', 'candidate', '戸田']);
  assert.equal(m['03'], undefined);
});
