const assert = require('node:assert/strict');
const fs = require('node:fs');
const { PGlite } = require(process.env.PGLITE_MODULE || '@electric-sql/pglite');

(async () => {
  const db = new PGlite();
  try {
    await db.exec('create role anon; create role authenticated; create role service_role bypassrls');
    await db.exec(fs.readFileSync('supabase/migrations/20261113100000_premium_daily.sql', 'utf8'));
    const store = async (through, value) => (await db.query(
      'select public.teilog_store_premium_snapshot($1) as stored', [{ through, value }]
    )).rows[0].stored;
    for (const role of ['anon', 'authenticated']) {
      await db.exec('set role ' + role);
      await assert.rejects(store('20261111', 1), /permission denied/);
      await assert.rejects(db.query('select * from public.teilog_premium_daily'), /permission denied/);
      await db.exec('reset role');
    }
    await db.exec('set role service_role');
    assert.equal(await store('20261111', 1), true);
    assert.equal(await store('20261111', 1), true);
    assert.equal(await store('20261111', 2), false);
    assert.equal(await store('20261110', 1), false);
    assert.equal(await store('20261112', 3), true);
    assert.equal(await store('20261111', 1), true);
    const beforeRace = await db.query("select data from public.teilog_premium_daily where through < '20261112' order by through desc limit 1");
    assert.deepEqual(beforeRace.rows[0].data, { through: '20261111', value: 1 });
    assert.equal(await store('20261231', 4), true);
    const retained = await db.query('select through from public.teilog_premium_daily');
    assert.deepEqual(retained.rows, [{ through: '20261231' }]);
    console.log('Premium DB role separation, idempotent retries and historical cutoff OK.');
  } finally {
    await db.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
