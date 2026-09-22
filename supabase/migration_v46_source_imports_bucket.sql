-- Private staging bucket for browser-uploaded DLT/ECO source files.
-- Server-side admin and import worker access this with the service role.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('source-imports', 'source-imports', false, 4194304, null)
on conflict (id) do update
set name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
