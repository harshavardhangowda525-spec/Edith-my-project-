-- =====================================================================
-- EDITH AI - Supabase PostgreSQL schema (V1)
-- Run in the Supabase SQL editor, or apply database/migrations in order.
-- Every row belongs to exactly one auth user; RLS enforces isolation for
-- any client using the anon key. The backend uses the service-role key and
-- additionally filters every query by user_id.
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------- user profiles ----------
create table if not exists public.profiles (
  id             uuid primary key references auth.users (id) on delete cascade,
  display_name   text check (char_length(display_name) <= 100),
  memory_enabled boolean not null default true,
  preferred_language text default 'en-US',
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- ---------- approved long-term memories ----------
create table if not exists public.memories (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  content    text not null check (char_length(content) between 1 and 1000),
  category   text not null default 'general' check (char_length(category) <= 50),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists memories_user_idx on public.memories (user_id, created_at desc);

-- ---------- conversations & messages (opt-in history; V1 does not auto-save) ----------
create table if not exists public.conversations (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  title      text check (char_length(title) <= 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists conversations_user_idx on public.conversations (user_id, updated_at desc);

create table if not exists public.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  user_id         uuid not null references auth.users (id) on delete cascade,
  role            text not null check (role in ('user', 'assistant')),
  content         text not null check (char_length(content) <= 16000),
  model           text,
  created_at      timestamptz not null default now()
);
create index if not exists messages_conversation_idx on public.messages (conversation_id, created_at);

-- ---------- knowledge documents & chunks ----------
create table if not exists public.knowledge_documents (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users (id) on delete cascade,
  title       text not null check (char_length(title) between 1 and 200),
  chunk_count integer not null default 0,
  created_at  timestamptz not null default now()
);
create index if not exists knowledge_documents_user_idx on public.knowledge_documents (user_id, created_at desc);

create table if not exists public.document_chunks (
  id          uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.knowledge_documents (id) on delete cascade,
  user_id     uuid not null references auth.users (id) on delete cascade,
  chunk_index integer not null,
  content     text not null,
  -- Full-text index for future server-side search; V1 ranks in the backend (BM25).
  fts         tsvector generated always as (to_tsvector('simple', content)) stored,
  created_at  timestamptz not null default now(),
  unique (document_id, chunk_index)
);
create index if not exists document_chunks_user_idx on public.document_chunks (user_id);
create index if not exists document_chunks_fts_idx on public.document_chunks using gin (fts);

-- ---------- updated_at trigger ----------
create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();
drop trigger if exists memories_touch on public.memories;
create trigger memories_touch before update on public.memories
  for each row execute function public.touch_updated_at();
drop trigger if exists conversations_touch on public.conversations;
create trigger conversations_touch before update on public.conversations
  for each row execute function public.touch_updated_at();

-- ---------- auto-create a profile for each new auth user ----------
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------- row-level security ----------
alter table public.profiles            enable row level security;
alter table public.memories            enable row level security;
alter table public.conversations       enable row level security;
alter table public.messages            enable row level security;
alter table public.knowledge_documents enable row level security;
alter table public.document_chunks     enable row level security;

drop policy if exists "own profile" on public.profiles;
create policy "own profile" on public.profiles
  for all to authenticated using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists "own memories" on public.memories;
create policy "own memories" on public.memories
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own conversations" on public.conversations;
create policy "own conversations" on public.conversations
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own messages" on public.messages;
create policy "own messages" on public.messages
  for all to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = auth.uid())
  );

drop policy if exists "own documents" on public.knowledge_documents;
create policy "own documents" on public.knowledge_documents
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own chunks" on public.document_chunks;
create policy "own chunks" on public.document_chunks
  for all to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (select 1 from public.knowledge_documents d where d.id = document_id and d.user_id = auth.uid())
  );

-- ---------- saved sales leads (added in migration 0002) ----------
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

-- ---------- background tasks (added in migration 0003) ----------
create table if not exists public.tasks (
  id           uuid primary key,
  user_id      uuid not null references auth.users (id) on delete cascade,
  type         text not null,
  title        text not null,
  params       jsonb not null default '{}'::jsonb,
  priority     integer not null default 5,
  status       text not null check (status in ('queued', 'running', 'paused', 'completed', 'failed', 'cancelled')),
  progress     integer not null default 0,
  message      text,
  result       text,
  error        text,
  attempts     integer not null default 0,
  max_attempts integer not null default 3,
  timeout_s    double precision not null default 600,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  finished_at  timestamptz
);
create index if not exists tasks_user_idx on public.tasks (user_id, created_at desc);
create index if not exists tasks_active_idx on public.tasks (status) where status in ('queued', 'running', 'paused');

alter table public.tasks enable row level security;
drop policy if exists "own tasks" on public.tasks;
create policy "own tasks" on public.tasks
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
