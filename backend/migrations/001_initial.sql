-- Initial schema, immutable after first application.

CREATE SEQUENCE batch_sequence;


CREATE TABLE blobs (
	sha256 VARCHAR(64) NOT NULL, 
	byte_size BIGINT NOT NULL, 
	storage_key TEXT NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sha256), 
	UNIQUE (storage_key)
)

;


CREATE TABLE subjects (
	student_id VARCHAR(64) NOT NULL, 
	password_hash TEXT NOT NULL, 
	must_change_password BOOLEAN NOT NULL, 
	banned BOOLEAN NOT NULL, 
	qq VARCHAR(64) NOT NULL, 
	phone VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (student_id)
)

;


CREATE TABLE batches (
	owner_id UUID NOT NULL, 
	sequence BIGINT DEFAULT nextval('batch_sequence') NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES subjects (id) ON DELETE CASCADE, 
	UNIQUE (sequence)
)

;


CREATE TABLE documents (
	original_blob_id UUID NOT NULL, 
	pdf_blob_id UUID, 
	source_ext VARCHAR(10) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	page_count INTEGER, 
	converter_version VARCHAR(100), 
	error_code VARCHAR(64), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(original_blob_id) REFERENCES blobs (id), 
	FOREIGN KEY(pdf_blob_id) REFERENCES blobs (id)
)

;


CREATE TABLE import_commits (
	owner_id UUID NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	result JSONB NOT NULL, 
	PRIMARY KEY (owner_id, key), 
	FOREIGN KEY(owner_id) REFERENCES subjects (id) ON DELETE CASCADE
)

;


CREATE TABLE sessions (
	token_hash VARCHAR(64) NOT NULL, 
	subject_id UUID NOT NULL, 
	csrf_token VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE
)

;


CREATE TABLE system_state (
	id INTEGER NOT NULL, 
	initialized BOOLEAN NOT NULL, 
	admin_subject_id UUID, 
	paused BOOLEAN NOT NULL, 
	settings JSONB NOT NULL, 
	settings_version INTEGER NOT NULL, 
	device JSONB NOT NULL, 
	device_checked_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CHECK (id = 1), 
	FOREIGN KEY(admin_subject_id) REFERENCES subjects (id)
)

;


CREATE TABLE document_grants (
	subject_id UUID NOT NULL, 
	document_id UUID NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (subject_id, document_id), 
	FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE, 
	FOREIGN KEY(document_id) REFERENCES documents (id)
)

;


CREATE TABLE idempotency_entries (
	subject_id UUID NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	batch_id UUID, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (subject_id, key), 
	FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE, 
	FOREIGN KEY(batch_id) REFERENCES batches (id) ON DELETE SET NULL
)

;


CREATE TABLE render_plans (
	owner_id UUID NOT NULL, 
	document_id UUID NOT NULL, 
	page_numbers INTEGER[] NOT NULL, 
	orientation VARCHAR(20) NOT NULL, 
	scaling VARCHAR(20) NOT NULL, 
	geometry JSONB NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	storage_key TEXT, 
	error_code VARCHAR(64), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES subjects (id) ON DELETE CASCADE, 
	FOREIGN KEY(document_id) REFERENCES documents (id)
)

;


CREATE TABLE print_tasks (
	batch_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	document_id UUID NOT NULL, 
	plan_id UUID NOT NULL, 
	copies INTEGER NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	state VARCHAR(20) NOT NULL, 
	parent_task_id UUID, 
	cancel_requested BOOLEAN NOT NULL, 
	cancel_confirmed BOOLEAN NOT NULL, 
	marker VARCHAR(100), 
	job_ref JSONB, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	diagnostic TEXT, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (batch_id, position), 
	CHECK (copies > 0), 
	FOREIGN KEY(batch_id) REFERENCES batches (id) ON DELETE CASCADE, 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(plan_id) REFERENCES render_plans (id), 
	FOREIGN KEY(parent_task_id) REFERENCES print_tasks (id) ON DELETE SET NULL, 
	UNIQUE (marker)
)

;


CREATE TABLE print_history (
	task_id UUID NOT NULL, 
	subject_id UUID NOT NULL, 
	total_pages INTEGER NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_id), 
	FOREIGN KEY(task_id) REFERENCES print_tasks (id) ON DELETE CASCADE, 
	FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE
)

;

CREATE INDEX ix_subjects_expires_at ON subjects (expires_at);

CREATE INDEX ix_documents_status ON documents (status);

CREATE INDEX ix_sessions_expires_at ON sessions (expires_at);

CREATE INDEX ix_sessions_subject_id ON sessions (subject_id);

CREATE INDEX ix_document_grants_document_id ON document_grants (document_id);

CREATE INDEX ix_document_grants_subject_id ON document_grants (subject_id);

CREATE INDEX ix_render_plans_status ON render_plans (status);

CREATE INDEX ix_print_tasks_state ON print_tasks (state);

CREATE INDEX ix_print_history_subject_id ON print_history (subject_id);

INSERT INTO system_state (id, initialized, paused, settings, settings_version, device) VALUES (1, false, false, '{}', 1, '{}');

CREATE TABLE login_throttle (bucket text PRIMARY KEY, started_at timestamptz NOT NULL, attempts integer NOT NULL);