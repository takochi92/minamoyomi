-- Built-in service credentials stay inside Edge Functions; VAPID/job keys in Vault.
begin;
create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;
create table teilog_private.push_runtime_state (
 singleton boolean primary key default true check(singleton),
 enabled boolean not null default false,
 last_run_at timestamptz,
 last_summary jsonb
);
alter table teilog_private.push_runtime_state enable row level security;
revoke all on teilog_private.push_runtime_state from public,anon,authenticated,service_role;
insert into teilog_private.push_runtime_state(singleton) values(true);
do $$ begin
 if not exists(select 1 from vault.secrets where name='teilog_push_job_key') then
  perform vault.create_secret(encode(extensions.gen_random_bytes(32),'hex'),'teilog_push_job_key','Private authentication for notification cron');
 end if;
end $$;

create function public.teilog_push_runtime() returns jsonb
language sql security definer set search_path='' as $$
 select jsonb_build_object(
 'enabled',(select enabled from teilog_private.push_runtime_state where singleton),
 'job_key',(select decrypted_secret from vault.decrypted_secrets where name='teilog_push_job_key'),
 'vapid',(select decrypted_secret::jsonb from vault.decrypted_secrets where name='teilog_push_vapid'));
$$;
revoke all on function public.teilog_push_runtime() from public,anon,authenticated;
grant execute on function public.teilog_push_runtime() to service_role;

create function public.teilog_push_init_keys(key_data jsonb) returns boolean
language plpgsql security definer set search_path='' as $$
begin
 if coalesce(key_data->>'publicKey','') !~ '^[A-Za-z0-9_-]{87}$' or coalesce(key_data->>'privateKey','') !~ '^[A-Za-z0-9_-]{43}$' then raise exception 'Invalid key data';end if;
 perform pg_advisory_xact_lock(20261027,1);
 if not exists(select 1 from vault.secrets where name='teilog_push_vapid') then
  perform vault.create_secret(key_data::text,'teilog_push_vapid','Encrypted notification signing key pair');
 end if;
 return true;
end $$;
revoke all on function public.teilog_push_init_keys(jsonb) from public,anon,authenticated;
grant execute on function public.teilog_push_init_keys(jsonb) to service_role;

create function public.teilog_push_finish(summary jsonb) returns void
language sql security definer set search_path='' as $$
 update teilog_private.push_runtime_state set last_run_at=now(),last_summary=jsonb_build_object(
 'sent',greatest(0,coalesce((summary->>'sent')::int,0)),
 'failed',greatest(0,coalesce((summary->>'failed')::int,0)),
 'skipped',greatest(0,coalesce((summary->>'skipped')::int,0))) where singleton;
$$;
revoke all on function public.teilog_push_finish(jsonb) from public,anon,authenticated;
grant execute on function public.teilog_push_finish(jsonb) to service_role;

create function teilog_private.queue_push(action text default 'morning') returns bigint
language plpgsql security definer set search_path='' as $$
declare request_id bigint;
begin
 if action not in ('morning','bootstrap') then raise exception 'Invalid job action';end if;
 select net.http_post(
  url:='https://xkibgkdniwlfocwpmuzy.supabase.co/functions/v1/favorite-morning',
  headers:=jsonb_build_object('Content-Type','application/json','X-Job-Key',(select decrypted_secret from vault.decrypted_secrets where name='teilog_push_job_key')),
  body:=jsonb_build_object('action',action),timeout_milliseconds:=90000) into request_id;
 return request_id;
end $$;
revoke all on function teilog_private.queue_push(text) from public,anon,authenticated,service_role;
-- Cron is installed only after deployment and bootstrap verification.
commit;
