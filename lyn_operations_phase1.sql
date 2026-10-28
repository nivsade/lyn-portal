-- LYN Operations | Phase 1 additive migration
-- Run in Supabase SQL Editor after taking a database backup.
-- No existing tables are dropped or altered.

create extension if not exists pgcrypto;

create table if not exists public.lyn_employer_details (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid not null unique references public.employers(id) on delete cascade,
  employer_identifier text,
  accounting_office text,
  payroll_contact_email text,
  employer_contact_email text,
  lyn_owner_name text,
  employee_count integer,
  monthly_price numeric(12,2),
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.lyn_powers_of_attorney (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid not null references public.employers(id) on delete cascade,
  insurance_company text not null,
  product_types text,
  has_signed_document text,
  drive_folder_url text,
  destination_email text,
  sent_status text,
  sent_at timestamptz,
  handling_status text,
  response_at timestamptz,
  email_thread_url text,
  notes text,
  source_sheet text,
  source_row integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(source_sheet, source_row)
);

create table if not exists public.lyn_unmatched_cases (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid references public.employers(id) on delete set null,
  employer_identifier text,
  employer_name text,
  managing_company_id text,
  fund_name text,
  product_type text,
  current_transaction_status text,
  error_type text,
  error_detail text,
  employee_identifier text,
  employee_first_name text,
  employee_last_name text,
  policy_number text,
  report_month text,
  salary_month text,
  contribution_components text,
  reported_contributions numeric(14,2),
  previous_status text,
  insurer_email text,
  source_file_name text,
  handling_status text,
  assigned_to uuid references public.profiles(id) on delete set null,
  notes text,
  source_sheet text,
  source_row integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(source_sheet, source_row)
);

create table if not exists public.lyn_tasks (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid references public.employers(id) on delete set null,
  unmatched_case_id uuid references public.lyn_unmatched_cases(id) on delete set null,
  power_of_attorney_id uuid references public.lyn_powers_of_attorney(id) on delete set null,
  title text not null,
  description text,
  status text not null default 'פתוחה',
  priority text not null default 'רגילה',
  assigned_to uuid references public.profiles(id) on delete set null,
  due_date date,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists lyn_poa_employer_idx on public.lyn_powers_of_attorney(employer_id);
create index if not exists lyn_cases_employer_idx on public.lyn_unmatched_cases(employer_id);
create index if not exists lyn_cases_employee_idx on public.lyn_unmatched_cases(employee_identifier);
create index if not exists lyn_tasks_employer_idx on public.lyn_tasks(employer_id);
create index if not exists lyn_tasks_assigned_idx on public.lyn_tasks(assigned_to, status, due_date);

-- Restrict the new tables from direct client access.
-- The existing portal uses a server-side Supabase admin client.
alter table public.lyn_employer_details enable row level security;
alter table public.lyn_powers_of_attorney enable row level security;
alter table public.lyn_unmatched_cases enable row level security;
alter table public.lyn_tasks enable row level security;
revoke all on public.lyn_employer_details from anon, authenticated;
revoke all on public.lyn_powers_of_attorney from anon, authenticated;
revoke all on public.lyn_unmatched_cases from anon, authenticated;
revoke all on public.lyn_tasks from anon, authenticated;
-- No RLS policies are added: only the server-side service-role client can access them.
-- Server code must check role in profiles before every read/write.
