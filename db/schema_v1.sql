-- InvestIQ PostgreSQL Schema v1
-- Per LLD Section 5: Data Model

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- M8: Core tables

CREATE TABLE investments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    asset_class VARCHAR(100),
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    team_id VARCHAR(100)
);

CREATE TABLE financial_models (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    investment_id UUID REFERENCES investments(id) ON DELETE CASCADE,
    file_path TEXT,
    original_filename VARCHAR(255),
    parsed_json JSONB,
    schema_version VARCHAR(20) DEFAULT '1.0',
    health_score FLOAT,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE scenarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_id UUID REFERENCES financial_models(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    assumptions_json JSONB,
    created_by VARCHAR(100),
    persona VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE analysis_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scenario_id UUID REFERENCES scenarios(id) ON DELETE CASCADE,
    agent_id VARCHAR(100),
    result_json JSONB,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cached in Redis with TTL 30 min for live sessions per strategy
CREATE INDEX idx_analysis_results_scenario ON analysis_results(scenario_id);
CREATE INDEX idx_analysis_results_agent ON analysis_results(agent_id);

CREATE TABLE model_assumptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_id UUID REFERENCES financial_models(id) ON DELETE CASCADE,
    key VARCHAR(255) NOT NULL,
    value TEXT,
    unit VARCHAR(50),
    source TEXT,
    is_hardcoded BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_model_assumptions_model ON model_assumptions(model_id);

-- Append-only audit log (strategy requires immutable audit trail)
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(100),
    user_id VARCHAR(100),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100),
    entity_id VARCHAR(100),
    payload JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Make audit_logs append-only with a rule
CREATE RULE audit_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING;
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_id);
CREATE INDEX idx_audit_logs_timestamp ON audit_logs(timestamp);

CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    investment_id UUID REFERENCES investments(id) ON DELETE CASCADE,
    report_type VARCHAR(50),
    audience VARCHAR(100),
    content_md TEXT,
    model_snapshot_id UUID,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    investment_id UUID REFERENCES investments(id) ON DELETE CASCADE,
    alert_type VARCHAR(100),
    threshold FLOAT,
    current_value FLOAT,
    severity VARCHAR(20),
    message TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alerts_active ON alerts(investment_id) WHERE resolved_at IS NULL;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    role VARCHAR(50) DEFAULT 'analyst',  -- admin, investment_manager, analyst, board, auditor
    persona_default VARCHAR(50),
    team_id VARCHAR(100)
);

-- M12: Market data (TimescaleDB logical mapping)
CREATE TABLE market_data_points (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    series_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    value FLOAT,
    source VARCHAR(100)
);

CREATE INDEX idx_market_data_series ON market_data_points(series_id, timestamp DESC);

-- If TimescaleDB extension is available:
-- SELECT create_hypertable('market_data_points', 'timestamp', if_not_exists => TRUE);
