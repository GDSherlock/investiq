"""SQLAlchemy ORM models — PostgreSQL schema per LLD Section 5."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Text, JSON,
    ForeignKey, Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from .database import Base


def generate_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Investment(Base):
    __tablename__ = "investments"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    asset_class = Column(String)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=utcnow)
    team_id = Column(String)

    models = relationship("FinancialModel", back_populates="investment")
    alerts = relationship("Alert", back_populates="investment")
    reports = relationship("Report", back_populates="investment")


class FinancialModel(Base):
    __tablename__ = "financial_models"

    id = Column(String, primary_key=True, default=generate_uuid)
    investment_id = Column(String, ForeignKey("investments.id"))
    file_path = Column(String)
    original_filename = Column(String)
    parsed_json = Column(JSON)
    schema_version = Column(String, default="1.0")
    health_score = Column(Float)
    uploaded_at = Column(DateTime, default=utcnow)
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=True)

    investment = relationship("Investment", back_populates="models")
    scenarios = relationship("Scenario", back_populates="model")
    assumptions = relationship("ModelAssumption", back_populates="model")


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(String, primary_key=True, default=generate_uuid)
    model_id = Column(String, ForeignKey("financial_models.id"))
    name = Column(String, nullable=False)
    assumptions_json = Column(JSON)
    created_by = Column(String)
    persona = Column(String)
    created_at = Column(DateTime, default=utcnow)

    model = relationship("FinancialModel", back_populates="scenarios")
    results = relationship("AnalysisResult", back_populates="scenario")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(String, primary_key=True, default=generate_uuid)
    scenario_id = Column(String, ForeignKey("scenarios.id"))
    agent_id = Column(String)
    result_json = Column(JSON)
    confidence = Column(Float)
    created_at = Column(DateTime, default=utcnow)

    scenario = relationship("Scenario", back_populates="results")


class ModelAssumption(Base):
    __tablename__ = "model_assumptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    model_id = Column(String, ForeignKey("financial_models.id"))
    key = Column(String, nullable=False)
    value = Column(String)
    unit = Column(String)
    source = Column(String)
    is_hardcoded = Column(Boolean, default=False)

    model = relationship("FinancialModel", back_populates="assumptions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String)
    user_id = Column(String)
    action = Column(String, nullable=False)
    entity_type = Column(String)
    entity_id = Column(String)
    payload = Column(JSON)
    timestamp = Column(DateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=generate_uuid)
    investment_id = Column(String, ForeignKey("investments.id"), nullable=True)
    report_type = Column(String)
    audience = Column(String)
    content_md = Column(Text)
    model_snapshot_id = Column(String)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=utcnow)

    investment = relationship("Investment", back_populates="reports")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=generate_uuid)
    investment_id = Column(String, ForeignKey("investments.id"))
    alert_type = Column(String)
    threshold = Column(Float)
    current_value = Column(Float)
    severity = Column(String)
    message = Column(Text)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    investment = relationship("Investment", back_populates="alerts")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True)
    role = Column(String, default="analyst")
    persona_default = Column(String)
    team_id = Column(String)
    password_hash = Column(String)
    created_at = Column(DateTime, default=utcnow)
    last_login = Column(DateTime, nullable=True)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=generate_uuid)
    model_id = Column(String, ForeignKey("financial_models.id"))
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    chunk_index = Column(Integer, nullable=False)
    section = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSON)
    created_at = Column(DateTime, default=utcnow)
    # Note: embedding column handled via raw SQL (pgvector type)


class MarketDataPoint(Base):
    __tablename__ = "market_data_points"

    id = Column(String, primary_key=True, default=generate_uuid)
    series_id = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    value = Column(Float)
    source = Column(String)
