-- Shared map overlays for PANO PRO (issue #20).
--
-- Backs the two-way overlay sync in pano_namer/services/overlay_sync.py, which
-- rides the existing area sync. Run this once in the Supabase SQL editor for
-- the same project that already holds shared_areas / shared_smart_settings.
-- Every PANO PRO machine talks to it with the anon key.
--
-- You ALSO need a storage bucket named "overlay-files" (mirrors "area-files").
-- Create it in Storage, or with the storage.buckets insert at the bottom.

create table if not exists public.shared_overlays (
    uid           text primary key,
    template_name text not null,
    display_name  text,
    bounds_json   text,
    width         integer,
    height        integer,
    crs           text,
    file_ext      text,
    file_hash     text,
    file_path     text,
    computer_name text,
    updated_at    timestamptz,
    deleted_at    timestamptz
);

create index if not exists shared_overlays_template_idx
    on public.shared_overlays (template_name);

alter table public.shared_overlays enable row level security;

drop policy if exists shared_overlays_anon_all on public.shared_overlays;
create policy shared_overlays_anon_all
    on public.shared_overlays
    for all
    to anon
    using (true)
    with check (true);

-- Storage bucket for the overlay image files (same shape as area-files).
insert into storage.buckets (id, name, public)
values ('overlay-files', 'overlay-files', true)
on conflict (id) do nothing;

drop policy if exists overlay_files_anon_all on storage.objects;
create policy overlay_files_anon_all
    on storage.objects
    for all
    to anon
    using (bucket_id = 'overlay-files')
    with check (bucket_id = 'overlay-files');
