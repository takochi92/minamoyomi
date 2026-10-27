// Local PostgreSQL execution; pass PGLITE_MODULE. Does not prove hosted auth setup.
const assert=require('node:assert/strict'),fs=require('fs');
const {PGlite}=require(process.env.PGLITE_MODULE||'@electric-sql/pglite');
(async()=>{const db=new PGlite();try{
await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;
create schema auth;create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
grant usage on schema auth to anon,authenticated,service_role;
grant execute on function auth.uid() to anon,authenticated,service_role;`);
await db.exec(fs.readFileSync('supabase/migrations/20261025_private_notes.sql','utf8'));
await db.exec(fs.readFileSync('supabase/migrations/20261027_morning_push.sql','utf8'));
const A='00000000-0000-4000-8000-000000000001',B='00000000-0000-4000-8000-000000000002',D='00000000-0000-4000-8000-000000000003';
await db.query('insert into auth.users values($1),($2)',[A,B]);
await db.query('insert into public.teilog_notes(user_id,data) values($1,$2),($3,$4)',[A,{racer:{},motor:{},fav:{'1234':{name:'Test A'}},bets:[],budget:0},B,{racer:{},motor:{},fav:{'5678':{name:'Test B'}},bets:[],budget:0}]);
const subscription={endpoint:'https://fcm.googleapis.com/fcm/send/test-only',keys:{p256dh:'a'.repeat(87),auth:'b'.repeat(22)}};
async function role(r,id=''){await db.exec('reset role');await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);await db.exec('set role '+r);}
async function save(owner=A,rev=0,on=true,s=subscription,rules={'1234':[4]}){return db.query('select public.teilog_save_push($1,$2,$3,$4,$5,$6) as revision',[D,s,rules,on,rev,owner]);}
await role('anon');await assert.rejects(db.query('select * from public.teilog_push_devices'),/permission denied/);
await assert.rejects(save(),/permission denied/);
await role('authenticated',A);assert.equal((await save()).rows[0].revision,1);
await assert.rejects(save(A,0),/Settings changed/);
await assert.rejects(save(A,1,true,subscription,{'1234':[7]}),/Invalid frame/);
await assert.rejects(save(A,1,true,{...subscription,endpoint:'https://localhost/x'}),/Invalid notification/);
await assert.rejects(db.query('update public.teilog_push_devices set enabled=false'),/permission denied/);
await role('authenticated',B);assert.equal((await db.query('select * from public.teilog_push_devices')).rows.length,0);
await assert.rejects(save(A,1),/Authentication changed/);
await assert.rejects(save(B,1),/Settings changed/);
await assert.rejects(db.query('select public.teilog_claim_push($1,$2,$3)',[D,'2026-10-27',1]),/permission denied/);
await role('service_role');
const claim=rev=>db.query('select public.teilog_claim_push($1,$2,$3) as claimed',[D,'2026-10-27',rev]);
assert.equal((await claim(2)).rows[0].claimed,false);
assert.equal((await claim(1)).rows[0].claimed,true);
assert.equal((await claim(1)).rows[0].claimed,false);
await role('authenticated',A);assert.equal((await save(A,1,false)).rows[0].revision,2);
await role('service_role');assert.equal((await claim(2)).rows[0].claimed,false);
await role('authenticated',B);
const D2='00000000-0000-4000-8000-000000000004';
assert.equal((await db.query('select public.teilog_save_push($1,$2,$3,true,0,$4) as revision',[D2,subscription,{'5678':[6]},B])).rows[0].revision,1,'Disabled old owner must not reserve a recycled endpoint');
await role('authenticated',A);await db.query('select public.teilog_delete_own_account($1)',[A]);
await db.exec('reset role');
assert.equal((await db.query('select count(*)::int as n from public.teilog_push_devices')).rows[0].n,1);
assert.equal((await db.query('select user_id from public.teilog_push_devices')).rows[0].user_id,B);
assert.equal((await db.query('select count(*)::int as n from public.teilog_push_deliveries')).rows[0].n,0);
assert.equal((await db.query('select count(*)::int as n from auth.users')).rows[0].n,1);
console.log('PostgreSQL: migration, anonymous denial, RLS A/B isolation, owner/revision guards, invalid endpoint/frame, service-only atomic deduplication, opt-out, deletion cascade passed');
}finally{await db.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
