-- Arrow style SAM.gov index for Supabase/Postgres.
-- Use this for a public read-only GitHub Pages search only after you review RLS policies.

create extension if not exists pg_trgm;

create table if not exists public.opportunities (
  id bigserial primary key,
  notice_id text unique not null,
  solicitation_number text,
  title text,
  posted_date date,
  response_deadline text,
  agency text,
  notice_type text,
  naics text,
  psc text,
  description text,
  sam_url text,
  source_json jsonb,
  first_seen_at timestamptz default now(),
  last_seen_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists public.documents (
  id bigserial primary key,
  notice_id text references public.opportunities(notice_id) on delete cascade,
  resource_id text,
  document_name text not null,
  extension text,
  format_group text,
  size_bytes bigint,
  agency text,
  posted_date date,
  notice_title text,
  solicitation_number text,
  notice_type text,
  download_url text,
  sam_url text,
  source_json jsonb,
  first_seen_at timestamptz default now(),
  last_seen_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(notice_id, resource_id)
);

create index if not exists opportunities_notice_id_idx on public.opportunities(notice_id);
create index if not exists opportunities_posted_date_idx on public.opportunities(posted_date desc);
create index if not exists opportunities_title_trgm_idx on public.opportunities using gin(title gin_trgm_ops);
create index if not exists opportunities_desc_trgm_idx on public.opportunities using gin(description gin_trgm_ops);
create index if not exists opportunities_agency_trgm_idx on public.opportunities using gin(agency gin_trgm_ops);
create index if not exists opportunities_naics_idx on public.opportunities(naics);
create index if not exists opportunities_psc_idx on public.opportunities(psc);

create index if not exists documents_notice_id_idx on public.documents(notice_id);
create index if not exists documents_resource_id_idx on public.documents(resource_id);
create index if not exists documents_posted_date_idx on public.documents(posted_date desc);
create index if not exists documents_extension_idx on public.documents(extension);
create index if not exists documents_format_group_idx on public.documents(format_group);
create index if not exists documents_name_trgm_idx on public.documents using gin(document_name gin_trgm_ops);
create index if not exists documents_notice_title_trgm_idx on public.documents using gin(notice_title gin_trgm_ops);
create index if not exists documents_agency_trgm_idx on public.documents using gin(agency gin_trgm_ops);

alter table public.opportunities enable row level security;
alter table public.documents enable row level security;

-- Optional public read policies for a GitHub Pages app using the anon key.
-- Only enable these if the indexed data is intended to be publicly searchable.
drop policy if exists "public read opportunities" on public.opportunities;
create policy "public read opportunities" on public.opportunities
  for select to anon using (true);

drop policy if exists "public read documents" on public.documents;
create policy "public read documents" on public.documents
  for select to anon using (true);
