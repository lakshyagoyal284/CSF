"""PostgreSQL persistence for applicants, asset declarations and assessments.

The reviewed DDL lives in ``db/schema.sql`` and is the source of truth for a
real deployment (migrations, constraints, comments, views). The SQLAlchemy
models here mirror it so the API can write assessments without raw SQL.

Design choices worth noting:

* **Optional by design.** With no ``ACS_DATABASE_URL`` the service runs fully
  stateless. Scoring never depends on the database, so a demo cannot be broken
  by an unconfigured database - failures are logged and reported as
  ``persisted: false``.
* **Enum-as-text.** Column types are declared as ``String`` here; the CHECK
  constraints and PostgreSQL enum types live in ``db/schema.sql``. This keeps
  the ORM importable without a live PostgreSQL instance and avoids the classic
  "enum type already exists" migration pain.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.config import get_settings
from backend.schemas import ScoreRequest, ScoreResponse

logger = logging.getLogger(__name__)

#: JSONB on PostgreSQL, plain JSON elsewhere (SQLite in tests). Chosen at
#: runtime from the dialect so the same models work for both.
JsonColumn = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Applicant(Base):
    """``applicants`` - personal and segment information."""

    __tablename__ = "applicants"

    applicant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(20))
    applicant_category: Mapped[str] = mapped_column(String(24), nullable=False)
    region_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    date_of_birth: Mapped[Any | None] = mapped_column(Date)
    age: Mapped[float | None] = mapped_column(Float)
    dependents: Mapped[int | None] = mapped_column(Integer)
    years_in_operation: Mapped[float | None] = mapped_column(Float)
    primary_crop: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssetRecord(Base):
    """``asset_records`` - declared tangible collateral."""

    __tablename__ = "asset_records"

    asset_record_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    applicant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("applicants.applicant_id", ondelete="CASCADE"), nullable=False
    )
    land_size_acres: Mapped[float | None] = mapped_column(Numeric(10, 2))
    irrigation_score: Mapped[float | None] = mapped_column(Float)
    soil_quality_score: Mapped[float | None] = mapped_column(Float)
    crop_yield_annual_value: Mapped[float | None] = mapped_column(Numeric(16, 2))
    land_market_value: Mapped[float | None] = mapped_column(Numeric(16, 2))
    property_value: Mapped[float | None] = mapped_column(Numeric(16, 2))
    equipment_value: Mapped[float | None] = mapped_column(Numeric(16, 2))
    livestock_value: Mapped[float | None] = mapped_column(Numeric(16, 2))
    shop_area_sqft: Mapped[float | None] = mapped_column(Numeric(10, 2))
    shop_space_ownership: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_applicable"
    )
    inventory_value: Mapped[float | None] = mapped_column(Numeric(16, 2))
    assessed_by: Mapped[str | None] = mapped_column(String(120))
    assessment_method: Mapped[str | None] = mapped_column(String(40))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CashflowProxy(Base):
    """``cashflow_proxies`` - alternative cash-flow evidence."""

    __tablename__ = "cashflow_proxies"

    cashflow_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    applicant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("applicants.applicant_id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[Any | None] = mapped_column(Date)
    period_end: Mapped[Any | None] = mapped_column(Date)
    monthly_upi_turnover: Mapped[float | None] = mapped_column(Numeric(16, 2))
    upi_txn_count_30d: Mapped[int | None] = mapped_column(Integer)
    utility_payment_consistency_score: Mapped[float | None] = mapped_column(Float)
    utility_payment_delays_12m: Mapped[int | None] = mapped_column(Integer)
    avg_monthly_bank_balance: Mapped[float | None] = mapped_column(Numeric(16, 2))
    annual_income_proxy: Mapped[float | None] = mapped_column(Numeric(16, 2))
    outstanding_debt: Mapped[float | None] = mapped_column(Numeric(16, 2))
    monthly_emi_obligation: Mapped[float | None] = mapped_column(Numeric(16, 2))
    requested_loan_amount: Mapped[float | None] = mapped_column(Numeric(16, 2))
    loan_tenure_months: Mapped[int | None] = mapped_column(Integer)
    data_source: Mapped[str | None] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CreditAssessmentLog(Base):
    """``credit_assessment_logs`` - every score, its reasons, and its audit trail."""

    __tablename__ = "credit_assessment_logs"

    assessment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    applicant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("applicants.applicant_id", ondelete="CASCADE"), nullable=False
    )

    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(24))

    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    probability_of_repayment: Mapped[float | None] = mapped_column(Numeric(7, 6))
    probability_of_default: Mapped[float | None] = mapped_column(Numeric(7, 6))
    risk_tier: Mapped[str] = mapped_column(String(12), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)

    recommended_credit_limit: Mapped[float | None] = mapped_column(Numeric(16, 2))
    recommended_incremental_limit: Mapped[float | None] = mapped_column(Numeric(16, 2))
    collateral_cap: Mapped[float | None] = mapped_column(Numeric(16, 2))
    income_cap: Mapped[float | None] = mapped_column(Numeric(16, 2))
    binding_constraint: Mapped[str | None] = mapped_column(String(16))
    ltv_applied: Mapped[float | None] = mapped_column(Numeric(5, 3))
    requested_amount_supported: Mapped[bool | None] = mapped_column(Boolean)
    indicative_rate_min: Mapped[float | None] = mapped_column(Numeric(5, 2))
    indicative_rate_max: Mapped[float | None] = mapped_column(Numeric(5, 2))

    derived_ratios: Mapped[dict[str, Any]] = mapped_column(JsonColumn, default=dict, nullable=False)
    shap_summary: Mapped[dict[str, Any]] = mapped_column(JsonColumn, default=dict, nullable=False)
    shap_top_factors: Mapped[list[dict[str, Any]]] = mapped_column(JsonColumn, default=list)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, default=dict, nullable=False)

    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scored_by: Mapped[str | None] = mapped_column(String(120))
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_assessment_applicant_scored_at", "applicant_id", "scored_at"),
        Index("idx_assessment_tier", "risk_tier"),
        Index("idx_assessment_score", "credit_score"),
    )


# ---------------------------------------------------------------------------
# engine / session management
# ---------------------------------------------------------------------------

_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine():
    """Create (once) the SQLAlchemy engine, or return ``None`` if unconfigured."""
    global _engine, _session_factory
    settings = get_settings()
    if not settings.database_url:
        return None
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,   # survives a dropped connection / restarted DB
            future=True,
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_session() -> Session | None:
    """Open a new session, or ``None`` when persistence is disabled."""
    get_engine()
    if _session_factory is None:
        return None
    return _session_factory()


def database_health() -> bool:
    """``True`` when the configured database answers a trivial query."""
    engine = get_engine()
    if engine is None:
        return False
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "not usable"
        logger.warning("Database health check failed: %s", exc)
        return False


def create_all() -> None:
    """Create tables from the ORM models (demo convenience; prefer ``db/schema.sql``)."""
    engine = get_engine()
    if engine is None:
        return
    Base.metadata.create_all(engine)
    logger.info("Created database tables from ORM models")


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def persist_assessment(
    request: ScoreRequest,
    response: ScoreResponse,
    *,
    scored_by: str | None = None,
    is_simulation: bool = False,
) -> int | None:
    """Write a scored application and its reasons to PostgreSQL.

    A single transaction covers the four tables, so an audit row can never be
    orphaned: either the applicant, the declarations, the cash-flow proxies and
    the assessment land together, or nothing does.

    Returns:
        The new ``assessment_id``, or ``None`` when persistence is disabled or
        the write failed (the API reports this as ``persisted: false`` rather
        than failing the scoring request).
    """
    session = get_session()
    if session is None:
        return None

    try:
        with session.begin():
            applicant_row = None
            if request.applicant.external_ref:
                applicant_row = session.execute(
                    select(Applicant).where(Applicant.external_ref == request.applicant.external_ref)
                ).scalar_one_or_none()

            if applicant_row is None:
                applicant_row = Applicant(
                    external_ref=request.applicant.external_ref,
                    full_name=request.applicant.full_name,
                    applicant_category=request.applicant.applicant_category,
                    region_tier=request.applicant.region_tier,
                    age=request.applicant.age,
                    dependents=request.applicant.dependents,
                    years_in_operation=request.applicant.years_in_operation,
                    primary_crop=request.applicant.crop_type,
                )
                session.add(applicant_row)
                session.flush()  # assign applicant_id
            else:
                # Keep the master record fresh without losing the original row.
                applicant_row.age = request.applicant.age or applicant_row.age
                applicant_row.dependents = (
                    request.applicant.dependents
                    if request.applicant.dependents is not None
                    else applicant_row.dependents
                )
                applicant_row.years_in_operation = (
                    request.applicant.years_in_operation or applicant_row.years_in_operation
                )

            session.add(
                AssetRecord(
                    applicant_id=applicant_row.applicant_id,
                    **{
                        **request.assets.model_dump(exclude={"shop_space_ownership"}),
                        # NOT NULL in the DDL, so an omitted segment-specific field
                        # must fall back to the explicit "not_applicable" level.
                        "shop_space_ownership": request.assets.shop_space_ownership
                        or "not_applicable",
                    },
                    assessed_by=scored_by,
                    assessment_method="officer_declaration",
                )
            )
            session.add(
                CashflowProxy(
                    applicant_id=applicant_row.applicant_id,
                    monthly_upi_turnover=request.cashflow.monthly_upi_turnover,
                    utility_payment_consistency_score=request.cashflow.utility_payment_consistency_score,
                    utility_payment_delays_12m=request.cashflow.utility_payment_delays_12m,
                    avg_monthly_bank_balance=request.cashflow.avg_monthly_bank_balance,
                    annual_income_proxy=request.cashflow.annual_income_proxy,
                    outstanding_debt=request.credit.outstanding_debt,
                    monthly_emi_obligation=request.credit.monthly_emi_obligation,
                    requested_loan_amount=request.credit.requested_loan_amount,
                    loan_tenure_months=request.credit.loan_tenure_months,
                    data_source="officer_declaration",
                )
            )

            log = CreditAssessmentLog(
                applicant_id=applicant_row.applicant_id,
                model_version=response.model_version,
                credit_score=response.credit_score,
                probability_of_repayment=response.probability_of_repayment,
                probability_of_default=response.probability_of_default,
                risk_tier=response.risk_tier,
                decision=response.decision,
                recommended_credit_limit=response.recommended_credit_limit,
                recommended_incremental_limit=response.recommended_incremental_limit,
                collateral_cap=response.collateral_cap,
                income_cap=response.income_cap,
                binding_constraint=response.binding_constraint,
                ltv_applied=response.ltv_applied,
                requested_amount_supported=response.requested_amount_supported,
                indicative_rate_min=response.indicative_rate_band.get("min_annual_rate"),
                indicative_rate_max=response.indicative_rate_band.get("max_annual_rate"),
                derived_ratios=response.derived_ratios,
                shap_summary={
                    "summary": response.explainability.summary,
                    "base_value_log_odds": response.explainability.base_value_log_odds,
                    "positive_factors": [
                        factor.model_dump() for factor in response.explainability.positive_factors
                    ],
                    "negative_factors": [
                        factor.model_dump() for factor in response.explainability.negative_factors
                    ],
                },
                shap_top_factors=[f.model_dump() for f in response.explainability.top_factors],
                input_payload=request.to_feature_payload(),
                is_simulation=is_simulation,
                scored_by=scored_by,
            )
            session.add(log)
            session.flush()
            return int(log.assessment_id)
    except Exception as exc:  # noqa: BLE001 - persistence must never break scoring
        logger.error("Failed to persist assessment: %s", exc, exc_info=True)
        return None
    finally:
        session.close()


def recent_assessments(limit: int = 20) -> list[dict[str, Any]]:
    """Latest assessments for the officer's activity panel."""
    session = get_session()
    if session is None:
        return []
    try:
        with session.begin():
            rows = session.execute(
                select(CreditAssessmentLog, Applicant.full_name)
                .join(Applicant, Applicant.applicant_id == CreditAssessmentLog.applicant_id)
                .order_by(CreditAssessmentLog.scored_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "assessment_id": int(log.assessment_id),
                    "applicant_name": name,
                    "credit_score": int(log.credit_score),
                    "risk_tier": log.risk_tier,
                    "decision": log.decision,
                    "recommended_credit_limit": float(log.recommended_credit_limit or 0),
                    "scored_at": log.scored_at.isoformat() if log.scored_at else None,
                    "scored_by": log.scored_by,
                }
                for log, name in rows
            ]
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read assessment history: %s", exc)
        return []
    finally:
        session.close()


def utcnow() -> datetime:
    """Timezone-aware UTC now (small helper used by callers/tests)."""
    return datetime.now(timezone.utc)
