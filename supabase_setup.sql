-- Run once in Supabase: SQL Editor -> New query -> paste -> Run.
-- One row per user: their draft picks (in order), favorites and dashboard settings.

create table if not exists public.user_state (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  picks      jsonb not null default '[]'::jsonb,
  fav        jsonb not null default '[]'::jsonb,
  settings   jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- Row level security: every user can read and write only their own row
alter table public.user_state enable row level security;

drop policy if exists "read own state" on public.user_state;
create policy "read own state" on public.user_state
  for select using (auth.uid() = user_id);

drop policy if exists "insert own state" on public.user_state;
create policy "insert own state" on public.user_state
  for insert with check (auth.uid() = user_id);

drop policy if exists "update own state" on public.user_state;
create policy "update own state" on public.user_state
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
