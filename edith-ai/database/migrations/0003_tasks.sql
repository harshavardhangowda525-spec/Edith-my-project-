-- Migration 0003: background task history (EDITH task engine).
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
