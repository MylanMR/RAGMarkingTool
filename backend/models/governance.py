"""ORM models for identity, policy, model endpoints, AI-assisted products,
and the hash-chained governance log. Shares the marking schema's Base.

As in the marking schema, no column that carries a classification has a
default: a product claim's marking is NULL until a human or the source
roll-up sets it, and submission refuses any NULL.
"""

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, CheckConstraint,
)
from sqlalchemy.orm import relationship

from backend.models.schema import Base, JsonList, _utcnow, _uuid

ROLES = ("author", "reviewer", "releaser", "admin", "ao", "auditor")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    username = Column(String(128), nullable=False, unique=True)
    display_name = Column(Text, nullable=False)
    auth_source = Column(String(16), nullable=False)  # local | ad | oidc | saml
    password_hash = Column(Text, nullable=True)        # local accounts only
    roles = Column(JsonList, nullable=False)
    clearance = Column(String(8), nullable=False)
    citizenship = Column(String(3), nullable=False)
    compartments = Column(JsonList, nullable=False)
    need_to_know_groups = Column(JsonList, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    must_change_password = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint("auth_source IN ('local','ad','oidc','saml')", name="ck_users_source"),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash = Column(String(64), primary_key=True)  # sha256 of the bearer token
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    version = Column(Integer, primary_key=True, autoincrement=False)
    settings = Column(JsonList, nullable=False)
    relaxed = Column(JsonList, nullable=False)        # setting keys made less strict
    justification = Column(Text, nullable=True)
    changed_by = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(128), nullable=False, unique=True)
    adapter = Column(String(32), nullable=False)
    base_url = Column(Text, nullable=False)
    model_id = Column(Text, nullable=False)
    max_classification = Column(String(8), nullable=False)
    credential_ref = Column(Text, nullable=True)       # env:NAME or file:/path, never the secret
    extra = Column(JsonList, nullable=False)           # adapter options (api_version, region...)
    enabled = Column(Boolean, nullable=False, default=False)
    created_by = Column(Text, nullable=False)
    approved_by = Column(Text, nullable=True)          # AO approval for non-local endpoints
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=_uuid)
    title = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    author_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    state = Column(String(16), nullable=False)
    # AI-assistance disclosure (always recorded, not configurable)
    model_endpoint_id = Column(String(36), nullable=False)
    model_name = Column(Text, nullable=False)
    adapter = Column(String(32), nullable=False)
    model_id_requested = Column(Text, nullable=False)
    model_id_reported = Column(Text, nullable=True)
    model_ceiling = Column(String(8), nullable=False)
    prompt_sha256 = Column(String(64), nullable=False)
    raw_output_sha256 = Column(String(64), nullable=False)
    withheld_chunk_ids = Column(JsonList, nullable=False)
    query_audit_id = Column(String(36), nullable=True)
    # workflow
    policy_version = Column(Integer, nullable=True)    # bound at submission
    banner_classification = Column(String(8), nullable=True)
    banner_controls = Column(JsonList, nullable=True)
    content_sha256 = Column(String(64), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_id = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    releaser_id = Column(String(36), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    return_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    claims = relationship("ProductClaim", order_by="ProductClaim.seq",
                          cascade="all, delete-orphan", back_populates="product")
    sources = relationship("ProductSource", order_by="ProductSource.num",
                           cascade="all, delete-orphan", back_populates="product")

    __table_args__ = (
        CheckConstraint("state IN ('draft','in_review','approved','released')",
                        name="ck_products_state"),
    )


class ProductClaim(Base):
    __tablename__ = "product_claims"

    id = Column(String(36), primary_key=True, default=_uuid)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    kind = Column(String(16), nullable=False)          # cited | uncited | judgment
    cited_sources = Column(JsonList, nullable=False)   # source numbers (1-based)
    invalid_refs = Column(JsonList, nullable=False)    # refs the model invented
    derived_marking = Column(Text, nullable=True)      # roll-up floor from cited sources
    portion_marking = Column(Text, nullable=True)      # NULL until set; submission refuses NULL
    classification = Column(String(8), nullable=True)
    dissem_controls = Column(JsonList, nullable=True)
    disposition = Column(String(32), nullable=True)
    disposition_by = Column(String(36), nullable=True)
    disposition_note = Column(Text, nullable=True)

    product = relationship("Product", back_populates="claims")

    __table_args__ = (
        CheckConstraint("kind IN ('cited','uncited','judgment')", name="ck_claims_kind"),
    )


class ProductSource(Base):
    __tablename__ = "product_sources"

    id = Column(String(36), primary_key=True, default=_uuid)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    num = Column(Integer, nullable=False)
    chunk_id = Column(String(36), nullable=False)
    parent_doc_id = Column(String(36), nullable=False)
    doc_title = Column(Text, nullable=False)
    source_system = Column(Text, nullable=False)
    portion_marking = Column(Text, nullable=False)
    classification = Column(String(8), nullable=False)
    dissem_controls = Column(JsonList, nullable=False)
    program = Column(Text, nullable=True)

    product = relationship("Product", back_populates="sources")


class GovernanceEvent(Base):
    """Hash-chained, append-only record of policy changes, model approvals,
    account administration, and every product workflow transition."""

    __tablename__ = "governance_events"

    seq = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    actor = Column(Text, nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    subject_type = Column(String(32), nullable=False)
    subject_id = Column(String(64), nullable=False, index=True)
    payload = Column(JsonList, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False)
