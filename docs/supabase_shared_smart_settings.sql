-- Shared Smart Mode settings for PANO PRO (issue #32).
--
-- Backs the two-way "ignore folders" sync in
-- pano_namer/services/ignore_folders_sync.py. Run this once in the Supabase
-- SQL editor for the same project that already holds shared_areas /
-- used_pano_names. Every PANO PRO machine talks to it with the anon key
-- (like the other shared tables), so the policies below grant the anon role
-- read/write on this single settings table.

create table if not exists public.shared_smart_settings (
    key           text primary key,
    value         jsonb       not null default '[]'::jsonb,
    computer_name text,
    updated_at    timestamptz not null default now()
);

alter table public.shared_smart_settings enable row level security;

-- All installs share one anon key; allow it to read and upsert settings rows.
drop policy if exists shared_smart_settings_anon_all on public.shared_smart_settings;
create policy shared_smart_settings_anon_all
    on public.shared_smart_settings
    for all
    to anon
    using (true)
    with check (true);
