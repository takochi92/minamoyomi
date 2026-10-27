-- Synthetic accounts and settings only, all rolled back.
begin;
select set_config('teilog.test_a',gen_random_uuid()::text,true),set_config('teilog.test_b',gen_random_uuid()::text,true),set_config('teilog.test_device',gen_random_uuid()::text,true);
insert into auth.users(id,email,aud,role) values
 (current_setting('teilog.test_a')::uuid,'push-'||current_setting('teilog.test_a')||'@example.invalid','authenticated','authenticated'),
 (current_setting('teilog.test_b')::uuid,'push-'||current_setting('teilog.test_b')||'@example.invalid','authenticated','authenticated');
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('teilog.test_a'),true);
select set_config('request.jwt.claims',jsonb_build_object('sub',current_setting('teilog.test_a'),'role','authenticated')::text,true);
select public.teilog_save_notes(0,'{"racer":{},"motor":{},"fav":{"1234":{"name":"Synthetic A"}},"bets":[],"budget":0}',current_setting('teilog.test_a')::uuid);
select public.teilog_save_push(current_setting('teilog.test_device')::uuid,
 jsonb_build_object('endpoint','https://fcm.googleapis.com/fcm/send/test-'||current_setting('teilog.test_device'),'keys',jsonb_build_object('p256dh',repeat('a',87),'auth',repeat('b',22))),
 '{"1234":[4],"9999":[1]}',true,0,current_setting('teilog.test_a')::uuid);
do $$ begin
 if (select count(*) from public.teilog_push_devices)<>1 then raise exception 'Owner read failed';end if;
 if (select rules from public.teilog_push_devices)<>'{"1234":[4]}'::jsonb then raise exception 'Non-favorite was not removed';end if;
 begin
  perform public.teilog_save_push(current_setting('teilog.test_device')::uuid,'{}','{}',true,1,current_setting('teilog.test_b')::uuid);
  raise exception 'Other owner accepted';
 exception when invalid_authorization_specification then null;end;
end $$;
select set_config('request.jwt.claim.sub',current_setting('teilog.test_b'),true);
select set_config('request.jwt.claims',jsonb_build_object('sub',current_setting('teilog.test_b'),'role','authenticated')::text,true);
do $$ begin
 if exists(select 1 from public.teilog_push_devices) then raise exception 'B read A settings';end if;
end $$;
reset role;
set local role service_role;
do $$ begin
 if not public.teilog_claim_push(current_setting('teilog.test_device')::uuid,current_date,1) then raise exception 'First claim failed';end if;
 if public.teilog_claim_push(current_setting('teilog.test_device')::uuid,current_date,1) then raise exception 'Duplicate claim accepted';end if;
 if not public.teilog_claim_push(current_setting('teilog.test_device')::uuid,current_date,1,'test') then raise exception 'Test claim blocks morning';end if;
end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('teilog.test_a'),true);
select set_config('request.jwt.claims',jsonb_build_object('sub',current_setting('teilog.test_a'),'role','authenticated')::text,true);
select public.teilog_save_notes(1,'{"racer":{},"motor":{},"fav":{},"bets":[],"budget":0}',current_setting('teilog.test_a')::uuid);
do $$ begin
 if (select rules from public.teilog_push_devices)<>'{}'::jsonb then raise exception 'Removed favorite retained';end if;
end $$;
select public.teilog_delete_own_account(current_setting('teilog.test_a')::uuid);
reset role;
do $$ begin
 if exists(select 1 from public.teilog_push_devices where id=current_setting('teilog.test_device')::uuid) then raise exception 'Deleted device retained';end if;
 if exists(select 1 from public.teilog_push_deliveries where device_id=current_setting('teilog.test_device')::uuid) then raise exception 'Deleted delivery retained';end if;
end $$;
rollback;
select 'PASS: hosted owner isolation, favorite-only copy, removal linkage, daily claims, test separation, deletion cascade; synthetic data rolled back' as result;
