create extension if not exists vector;

create table documents (
    id text primary key,
    storage_object_key text not null,
    file_sha256 text not null,
    drug_name text not null,
    manufacturer text not null,
    formulation text,
    chunk_count integer not null,
    ingested_at timestamptz not null default now()
);

create table chunks (
    id bigserial primary key,
    document_id text not null references documents (id) on delete cascade,
    content text not null,
    content_sha256 text not null,
    embedding vector(1536) not null,
    tsv tsvector generated always as (to_tsvector('english', content)) stored,
    section_number text,
    section_title text,
    page_start integer not null,
    page_end integer not null,
    chunk_index integer not null,
    chunk_type text not null check (chunk_type in ('text', 'table')),
    unique (document_id, content_sha256) -- reconciliation key
);

create index chunks_embedding_hnsw on chunks using hnsw (embedding vector_cosine_ops);
create index chunks_tsv_gin on chunks using gin (tsv);

create table conversations (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    created_at timestamptz not null default now()
);

create table messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations (id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    sources jsonb,
    created_at timestamptz not null default now()
);

-- Postgres does not index foreign keys automatically; conversation loads read
-- messages by conversation in creation order.
create index messages_by_conversation on messages (conversation_id, created_at);
