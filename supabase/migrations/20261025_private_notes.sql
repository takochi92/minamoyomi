-- Apply in the dedicated, empty Teilog project. No public notes or service key.
begin;
create table if not exists public.teilog_notes (
  user_id uuid primary key references auth.users(id) on delete cascade,
  revision bigint not null default 1 check (revision > 0),
  data jsonb not null,
  updated_at timestamptz not null default now(),
  constraint teilog_note_size check (octet_length(data::text) <= 2000000),
  constraint teilog_note_shape check (
    jsonb_typeof(data) = 'object'
    and jsonb_typeof(data->'racer') = 'object'
    and jsonb_typeof(data->'motor') = 'object'
    and jsonb_typeof(data->'fav') = 'object'
    and jsonb_typeof(data->'bets') = 'array'
    and jsonb_typeof(data->'budget') = 'number'
    and data ?& array['racer','motor','fav','bets','budget']
    and data - array['racer','motor','fav','bets','budget'] = '{}'::jsonb
  )
);
alter table public.teilog_notes enable row level security;
revoke all on public.teilog_notes from anon, authenticated;
grant select on public.teilog_notes to authenticated;
drop policy if exists "Read own notes" on public.teilog_notes;
create policy "Read own notes" on public.teilog_notes for select to authenticated
using ((select auth.uid()) = user_id);

-- The JWT determines the owner. expected_user_id is an additional guard against
-- an account switch while the browser is preparing an asynchronous request.
-- Compare-and-swap rejects stale writes, including from two different devices.
create or replace function public.teilog_save_notes(expected_revision bigint, note_data jsonb, expected_user_id uuid)
returns bigint language plpgsql security definer set search_path = '' as $$
declare
  owner_id uuid := auth.uid();
  saved_revision bigint;
begin
  if owner_id is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if expected_user_id is distinct from owner_id then raise exception 'Account changed' using errcode = '28000'; end if;
  if expected_revision < 0 or note_data is null then raise exception 'Invalid note' using errcode = '22023'; end if;
  if expected_revision = 0 then
    insert into public.teilog_notes (user_id, revision, data)
      values (owner_id, 1, note_data) on conflict (user_id) do nothing
      returning revision into saved_revision;
  else
    update public.teilog_notes set data = note_data, revision = revision + 1, updated_at = now()
      where user_id = owner_id and revision = expected_revision
      returning revision into saved_revision;
  end if;
  if saved_revision is null then raise exception 'Note changed on another device' using errcode = '40001'; end if;
  return saved_revision;
end $$;
revoke all on function public.teilog_save_notes(bigint, jsonb, uuid) from public, anon;
grant execute on function public.teilog_save_notes(bigint, jsonb, uuid) to authenticated;

-- Explicit self-service account deletion. Cascades only this user's notes.
create or replace function public.teilog_delete_own_account(expected_user_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
declare owner_id uuid := auth.uid();
begin
  if owner_id is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if expected_user_id is distinct from owner_id then raise exception 'Account changed' using errcode = '28000'; end if;
  delete from auth.users where id = owner_id;
end $$;
revoke all on function public.teilog_delete_own_account(uuid) from public, anon;
grant execute on function public.teilog_delete_own_account(uuid) to authenticated;
commit;
