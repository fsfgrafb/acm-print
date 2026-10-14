-- A QQ identifier is not an email address. Preserve old values separately.
ALTER TABLE subjects RENAME COLUMN qq TO legacy_qq;
ALTER TABLE subjects ALTER COLUMN legacy_qq SET DEFAULT '';
ALTER TABLE subjects ADD COLUMN email VARCHAR(254) NOT NULL DEFAULT '';
