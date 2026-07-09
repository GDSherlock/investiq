-- InvestIQ Schema v2 Migration: pgvector + auth + traceability
-- Run after schema_v1.sql

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Add password_hash to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;

-- Add uploaded_by (user_id) to financial_models for traceability
ALTER TABLE financial_models ADD COLUMN IF NOT EXISTS uploaded_by UUID REFERENCES users(id);

-- Vector embeddings store
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_id UUID REFERENCES financial_models(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    chunk_index INTEGER NOT NULL,
    section VARCHAR(100) NOT NULL,         -- e.g. 'cover', 'assumptions', 'returns', 'sensitivity'
    content TEXT NOT NULL,                   -- raw text content of the chunk
    metadata JSONB,                         -- source sheet, row range, keys, etc.
    embedding vector(1536),                 -- Azure OpenAI text-embedding-ada-002 dimension
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for similarity search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_chunks_model ON document_chunks(model_id);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON document_chunks(section);

-- Insert default admin user (password: admin123)
INSERT INTO users (id, name, email, role, password_hash)
VALUES (
    uuid_generate_v4(),
    'Admin User',
    'admin@investiq.com',
    'admin',
    '$2b$12$jtez1d7ym4HDeHZSgXWRJedVg6lVcpNPMlEP8xkC76heV8GC/NQHy'
) ON CONFLICT (email) DO NOTHING;

-- Insert demo users
INSERT INTO users (id, name, email, role, persona_default, password_hash)
VALUES
    (uuid_generate_v4(), 'Investment Manager', 'im@investiq.com', 'investment_manager', 'IM',
     '$2b$12$XsvxSm5NWSaoqqIL2ZMce.7MYG5CrkRYCcSojaciz1wAWwIw.cQYG'),
    (uuid_generate_v4(), 'CFO User', 'cfo@investiq.com', 'analyst', 'CF',
     '$2b$12$XsvxSm5NWSaoqqIL2ZMce.7MYG5CrkRYCcSojaciz1wAWwIw.cQYG'),
    (uuid_generate_v4(), 'Board Director', 'board@investiq.com', 'board', 'BD',
     '$2b$12$XsvxSm5NWSaoqqIL2ZMce.7MYG5CrkRYCcSojaciz1wAWwIw.cQYG')
ON CONFLICT (email) DO NOTHING;
