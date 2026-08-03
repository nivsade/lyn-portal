-- Run this entire file once in Supabase > SQL Editor.
create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null,
  email text not null unique,
  role text not null check (role in ('admin','referent','payroll')),
  office_name text,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.employers (
  id uuid primary key default gen_random_uuid(),
  employer_number text unique,
  name text not null,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.user_employers (
  user_id uuid not null references public.profiles(id) on delete cascade,
  employer_id uuid not null references public.employers(id) on delete cascade,
  primary key (user_id, employer_id)
);

create table if not exists public.uploads (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid not null references public.employers(id) on delete cascade,
  report_month date not null,
  file_name text not null,
  storage_path text not null unique,
  uploaded_by uuid not null references public.profiles(id),
  uploaded_at timestamptz not null default now(),
  file_size bigint,
  notes text,
  unique (employer_id, report_month)
);

create index if not exists idx_uploads_employer_month on public.uploads(employer_id, report_month);
create index if not exists idx_user_employers_user on public.user_employers(user_id);

-- Automatically create a basic profile after signup.
-- Admin can later change role, name and office in the app.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, full_name, email, role)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email,'@',1)),
    new.email,
    'payroll'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();

alter table public.profiles enable row level security;
alter table public.employers enable row level security;
alter table public.user_employers enable row level security;
alter table public.uploads enable row level security;

-- The Streamlit backend uses the service-role key, which is kept only in server secrets.
-- Direct client access remains blocked unless policies are added later.

insert into storage.buckets (id, name, public)
values ('xml-files', 'xml-files', false)
on conflict (id) do update set public = false;
