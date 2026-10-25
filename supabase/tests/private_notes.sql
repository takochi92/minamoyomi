-- Run after migration in the dedicated project SQL editor.
-- All synthetic users, notes and deletion checks are rolled back.
begin;
do $$ begin
  if exists (select 1 from auth.users where id in ('00000000-0000-4000-8000-00000000a001','00000000-0000-4000-8000-00000000b001')) then
    raise exception 'Synthetic test IDs already exist; aborting without changing them';
  end if;
  if has_table_privilege('anon','public.teilog_notes','select') then raise exception 'Anonymous table access'; end if;
  if has_table_privilege('authenticated','public.teilog_notes','update') then raise exception 'Direct writes bypass CAS'; end if;
  if has_function_privilege('anon','public.teilog_save_notes(bigint,jsonb,uuid)','execute') then raise exception 'Anonymous write RPC'; end if;
end $$;
insert into auth.users(id,email,aud,role) values
 ('00000000-0000-4000-8000-00000000a001','note-test-a@example.invalid','authenticated','authenticated'),
 ('00000000-0000-4000-8000-00000000b001','note-test-b@example.invalid','authenticated','authenticated');
set local role authenticated;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-00000000a001',true);
select set_config('request.jwt.claims','{"sub":"00000000-0000-4000-8000-00000000a001","role":"authenticated"}',true);
select public.teilog_save_notes(0,'{"racer":{"1234":{"name":"テストA","text":"非公開A"}},"motor":{},"fav":{},"bets":[],"budget":0}', '00000000-0000-4000-8000-00000000a001');
do $$ begin
  if (select count(*) from public.teilog_notes) <> 1 then raise exception 'Owner cannot read notes'; end if;
  begin
    perform public.teilog_save_notes(0,'{"racer":{},"motor":{},"fav":{},"bets":[],"budget":0}','00000000-0000-4000-8000-00000000a001');
    raise exception 'Stale write was accepted';
  exception when serialization_failure then null; end;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-00000000b001',true);
select set_config('request.jwt.claims','{"sub":"00000000-0000-4000-8000-00000000b001","role":"authenticated"}',true);
do $$ begin
  if exists(select 1 from public.teilog_notes) then raise exception 'B can read A notes'; end if;
  begin
    perform public.teilog_save_notes(0,'{"racer":{},"motor":{},"fav":{},"bets":[],"budget":0}','00000000-0000-4000-8000-00000000a001');
    raise exception 'Switched account write accepted';
  exception when invalid_authorization_specification then null; end;
  begin
    perform public.teilog_delete_own_account('00000000-0000-4000-8000-00000000a001');
    raise exception 'Cross-account delete accepted';
  exception when invalid_authorization_specification then null; end;
end $$;
select public.teilog_save_notes(0,'{"racer":{},"motor":{},"fav":{},"bets":[],"budget":2000}','00000000-0000-4000-8000-00000000b001');
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-00000000a001',true);
select set_config('request.jwt.claims','{"sub":"00000000-0000-4000-8000-00000000a001","role":"authenticated"}',true);
select public.teilog_delete_own_account('00000000-0000-4000-8000-00000000a001');
reset role;
do $$ begin
  if exists(select 1 from auth.users where id='00000000-0000-4000-8000-00000000a001') then raise exception 'Self-delete failed'; end if;
  if exists(select 1 from public.teilog_notes where user_id='00000000-0000-4000-8000-00000000a001') then raise exception 'Deleted notes retained'; end if;
  if not exists(select 1 from auth.users where id='00000000-0000-4000-8000-00000000b001') then raise exception 'Other account was deleted'; end if;
end $$;
rollback;
select 'PASS: anonymous denial, owner access, RLS isolation, CAS, account switch guard, self-delete cascade (test data rolled back)' as result;
