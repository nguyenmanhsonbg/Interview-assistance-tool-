ALTER TABLE assessment_snapshots
    ADD COLUMN assessment_input_source TEXT NOT NULL DEFAULT 'EXCEL_IMPORT'
        CHECK (assessment_input_source IN ('EXCEL_IMPORT', 'HTML_IMPORT'));

ALTER TABLE assessment_snapshots
    ADD COLUMN source_file_sha256 TEXT
        CHECK (source_file_sha256 IS NULL OR length(source_file_sha256) = 64);

ALTER TABLE assessment_snapshots
    ADD COLUMN package_id TEXT;

UPDATE assessment_snapshots
SET source_file_sha256 = workbook_sha256
WHERE source_file_sha256 IS NULL;

CREATE UNIQUE INDEX ix_assessment_snapshots_package_id
    ON assessment_snapshots(package_id)
    WHERE package_id IS NOT NULL;
