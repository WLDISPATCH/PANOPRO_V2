# Shared Pano Naming — Supabase Setup

Shared Pano Naming lets two or three PanoPro desktop installs share rename
numbering through one small Supabase table, so two computers never produce the
same pano name (like `260702_OPTA_004`). Only the used names are shared —
photos, projects, DXFs, and the local PanoPro database stay on each computer.

## 1. Create the table (run once)

Open your Supabase project → SQL Editor → run:

```sql
create table if not exists used_pano_names (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  date_code text not null,
  area_code text not null,
  sequence_number integer not null,
  computer_name text,
  created_at timestamptz default now()
);

create index if not exists idx_used_pano_names_prefix
  on used_pano_names (date_code, area_code, sequence_number desc);

alter table used_pano_names enable row level security;

create policy "anon select" on used_pano_names
  for select to anon using (true);

create policy "anon insert" on used_pano_names
  for insert to anon with check (true);

-- Required when "Automatically expose new tables" is disabled in the
-- project's Data API settings (the recommended setting): grant the anon
-- role access to this one table explicitly.
grant usage on schema public to anon;
grant select, insert on used_pano_names to anon;
```

Recommended Data API settings for the Supabase project:

- **Enable Data API**: on — PanoPro uses this REST API directly.
- **Automatically expose new tables**: off — the grants above expose only
  `used_pano_names`.
- **Enable automatic RLS**: on — extra safety; the SQL above also enables RLS
  explicitly.

The unique `name` column is the duplicate guard: the same pano name can never
be inserted twice, even if two computers export at almost the same moment.

## 2. Configure each PanoPro install

In PanoPro open **Settings → Shared Pano Naming** and fill in:

- **Enable shared pano naming**: on
- **Supabase URL**: your project URL, e.g. `https://yourproject.supabase.co`
  (Supabase dashboard → Project Settings → API)
- **Supabase anon key**: the `anon` / `public` API key from the same page
- **Computer name**: defaults to the Windows computer name; editable

Press **Test Connection**. It should report Connected.

## 3. How exports behave

- With shared naming on, the rename confirmation shows the prefix, photo
  count, and the starting number (e.g. `260702_OPTA: 5 photos, names begin at
  006.`), and the button reads **Reserve Names and Export**.
- Names are inserted into Supabase *before* any local file is renamed. If two
  computers race, one insert is rejected; PanoPro automatically re-checks the
  highest number and takes the next free range. Occasional skipped numbers are
  normal and harmless.
- If Supabase cannot be reached while shared naming is enabled, the export is
  blocked with a clear message. Reconnect or disable shared naming for that
  export — PanoPro never silently numbers locally while sharing is on.

## 4. Bringing in older folders

For photos that were named before shared naming existed (e.g.
`260702_OPTA_045.jpg`): import them into a template, then press
**Scan & Add Existing Names** in Settings → Shared Registry. Every recognized
name in the template is added to Supabase once; names that already exist are
skipped, so the button is safe to press repeatedly.

## 5. Area sync (optional)

With **Sync areas between computers** enabled in Settings, area files (DXF/KML,
including drawn areas which are auto-exported as KML) upload to Supabase
Storage, and templates **with the same name** stay in sync on every computer:
new areas appear automatically, changed files are pulled on the next app
open/refresh, and deletions propagate. Photos, overlays, and the local
database never sync.

Run this once in the SQL Editor (in addition to the setup above):

```sql
create table if not exists shared_areas (
  uid text primary key,
  template_name text not null,
  name text not null,
  display_color text,
  file_ext text not null,
  file_hash text not null,
  file_path text not null,
  computer_name text,
  updated_at timestamptz not null,
  deleted_at timestamptz
);
alter table shared_areas enable row level security;
create policy "anon areas select" on shared_areas for select to anon using (true);
create policy "anon areas insert" on shared_areas for insert to anon with check (true);
create policy "anon areas update" on shared_areas for update to anon using (true);
grant usage on schema public to anon;
grant select, insert, update on shared_areas to anon;

insert into storage.buckets (id, name) values ('area-files', 'area-files')
  on conflict (id) do nothing;
create policy "anon area files select" on storage.objects
  for select to anon using (bucket_id = 'area-files');
create policy "anon area files insert" on storage.objects
  for insert to anon with check (bucket_id = 'area-files');
create policy "anon area files update" on storage.objects
  for update to anon using (bucket_id = 'area-files');
```

Notes:

- Sync is two-way with "newest edit wins". Occasional conflicts resolve to the
  most recent change; nothing is ever deleted from disk (local deletes are
  soft and recoverable).
- Blank areas (no geometry) stay local — there is no file to share.
- If Supabase is unreachable, the app keeps working; areas simply sync on the
  next successful run (see the result line under Settings).
