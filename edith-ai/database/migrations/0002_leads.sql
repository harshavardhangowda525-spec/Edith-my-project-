-- Migration 0002: saved sales leads (businesses without a website, from the lead finder).
create table if not exists public.leads (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references auth.users (id) on delete cascade,
  place_id            text not null,
  name                text not null check (char_length(name) <= 300),
  phone               text,
  phone_international text,
  address             text,
  rating              numeric,
  reviews             integer,
  maps_url            text,
  social_url          text,
  query               text,
  status              text not null default 'new' check (status in ('new', 'called', 'interested', 'not_interested', 'won')),
  notes               text check (char_length(notes) <= 2000),
  created_at          timestamptz not null default now(),
  unique (user_id, place_id)
);
create index if not exists leads_user_idx on public.leads (user_id, created_at desc);

alter table public.leads enable row level security;
drop policy if exists "own leads" on public.leads;
create policy "own leads" on public.leads
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
