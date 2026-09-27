-- Preserve the generated snapshot marker alongside tenant document versions.
BEGIN;
ALTER TABLE v7_private.document_versions DROP CONSTRAINT document_versions_filename_check;
ALTER TABLE v7_private.document_versions ADD CONSTRAINT document_versions_filename_check
  CHECK (filename = '_snapshot.json' OR filename ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$');
INSERT INTO v7_private.schema_version VALUES (5) ON CONFLICT DO NOTHING;
COMMIT;
