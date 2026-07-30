from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings owned by the product API."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "HelloAgents Learn"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    database_url: str = (
        "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/hello_agents"
    )
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("./storage")

    product_embedding_provider: str = "dashscope"
    product_embedding_model: str = "text-embedding-v4"
    product_embedding_dimension: int = Field(default=1024, gt=0)
    product_embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    )
    product_embedding_api_key: str | None = None
    product_embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    product_collection_name: str = "learn_platform_source_chunks_v1"
    ingestion_queue_name: str = "learn-platform-ingestion"
    course_generation_queue_name: str = "learn-platform-course-generation"
    workspace_deletion_queue_name: str = "learn-platform-workspace-deletion"
    tutor_queue_name: str = "learn-platform-tutor"
    # Stage 3 baseline Tutor budget — kept for offline paired eval and the
    # historical (pre-Slice-3) retry path only; NOT a user-selectable option.
    tutor_max_evidence_tokens: int = Field(default=8_000, gt=0)
    tutor_max_output_tokens: int = Field(default=2_000, gt=0)
    # Slice 3 diagnostic-scaffold skill budget for every new turn (Spec 003 §9).
    tutor_skill_max_evidence_tokens: int = Field(default=10_000, gt=0)
    tutor_skill_max_output_tokens: int = Field(default=3_000, gt=0)
    practice_queue_name: str = "learn-platform-practice"
    # Slice 5 (Spec 005 §7.2 / ADR 007 §3.6): a single authoritative budget.
    # provider calls total 4 (plan + initial + structure repair + specialized
    # repair); attempt steps 12; searches 3. The old dual denomination
    # (separate eval 6-step vs runtime 20-step) and the dead per-item ref-call
    # setting were removed.
    practice_generation_max_searches: int = Field(default=3, ge=1)
    practice_generation_max_provider_calls: int = Field(default=4, ge=1)
    practice_generation_max_attempt_steps: int = Field(default=12, ge=1)
    practice_generation_max_evidence_tokens: int = Field(default=24_000, gt=0)
    # Per provider call. The attempt-wide ceiling is enforced by the separate
    # provider-call budget; reusing this value as a cumulative post-call limit
    # discards output that has already been paid for.
    practice_generation_max_output_tokens: int = Field(default=12_000, gt=0)
    practice_generation_search_top_k: int = Field(default=5, gt=0, le=5)
    practice_generation_timeout_seconds: float = Field(default=180.0, gt=0)
    practice_generation_max_wall_seconds: int = Field(default=600, gt=0)
    practice_grading_max_provider_calls: int = Field(default=2, ge=1)
    practice_grading_max_evidence_tokens: int = Field(default=12_000, gt=0)
    # Per provider call; practice_grading_max_provider_calls bounds the attempt.
    practice_grading_max_output_tokens: int = Field(default=3_000, gt=0)
    practice_grading_timeout_seconds: float = Field(default=60.0, gt=0)
    practice_grading_max_wall_seconds: int = Field(default=180, gt=0)
    practice_short_answer_max_chars: int = Field(default=8_000, gt=0)
    ingestion_lease_seconds: int = Field(default=120, gt=1)
    ingestion_heartbeat_seconds: int = Field(default=30, gt=0)
    ingestion_max_attempts: int = Field(default=3, ge=1)
    ingestion_reconcile_seconds: int = Field(default=30, gt=0)
    document_max_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    batch_max_files: int = Field(default=20, gt=0)
    batch_max_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    pdf_max_pages: int = Field(default=500, gt=0)
    parsed_text_max_chars: int = Field(default=1_000_000, gt=0)
    document_max_chunks: int = Field(default=2_000, gt=0)
    document_embedding_max_tokens: int = Field(default=1_500_000, gt=0)
    parser_timeout_seconds: int = Field(default=600, gt=0)
    workspace_max_active_ingestions: int = Field(default=3, gt=0)
    product_rag_default_top_k: int = Field(default=5, gt=0, le=20)
    product_rag_candidate_multiplier: int = Field(default=3, gt=0)
    product_rag_candidate_cap: int = Field(default=50, gt=0)
    product_rag_min_score: float | None = Field(default=0.50, ge=-1, le=1)
    product_generation_provider: str = "deepseek"
    product_generation_model: str = "deepseek-v4-flash"
    product_generation_base_url: str = "https://api.deepseek.com"
    product_generation_api_key: str | None = None
    product_generation_timeout_seconds: float = Field(default=45.0, gt=0)
    product_generation_thinking: bool = False
    product_generation_max_evidence_tokens: int = Field(default=12_000, gt=0)
    product_generation_max_output_tokens: int = Field(default=1_500, gt=0)
    # Correction 002 §2 / Spec 005 §7.2: independent model for practice
    # generation and generation-period repair. Default deepseek-v4-pro for
    # improved Java/C++ success rate. Tutor, course generation, RAG answer
    # and practice grading continue using product_generation_model.
    practice_generation_model: str = "deepseek-v4-pro"
    lesson_generation_max_evidence_tokens: int = Field(default=48_000, gt=0)
    lesson_generation_max_output_tokens_per_call: int = Field(default=8_000, gt=0)
    lesson_generation_max_total_output_tokens: int = Field(default=32_000, gt=0)
    lesson_generation_max_provider_calls: int = Field(default=12, ge=4)
    lesson_generation_max_coverage_units: int = Field(default=8, ge=1, le=8)
    lesson_generation_timeout_seconds: float = Field(default=180.0, gt=0)
    lesson_generation_max_wall_seconds: int = Field(default=1_200, gt=0)

    request_id_header: str = "X-Request-ID"
    readiness_timeout_seconds: float = 2.0

    # Slice 4: MCP execution adapter (Spec 004 §5, ADR 006 §2.2)
    mcp_execution_adapter_url: str | None = None  # internal adapter service URL
    code_lab_queue_name: str = "learn-platform-code-lab"
    code_lab_lease_seconds: int = Field(default=120, gt=1)
    code_lab_heartbeat_seconds: int = Field(default=30, gt=0)
    code_lab_max_attempts: int = Field(default=3, ge=1)
    code_lab_execution_timeout_seconds: float = Field(default=15.0, gt=0)

    # Slice 4: Wolfram science tool (Spec 004 §6, ADR 006 §2.2)
    wolfram_mcp_enabled: bool = False
    wolfram_mcp_url: str = "https://agenttools.wolfram.com/mcp"
    wolfram_mcp_api_key: str | None = None
    wolfram_mcp_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    wolfram_mcp_call_timeout_seconds: float = Field(default=30.0, gt=0)
    wolfram_max_calls_per_turn: int = Field(default=3, ge=1)

    # Slice 4 packet 002: dual Tool budgets (Spec 004 §12, ADR 006 §3)
    tutor_max_mcp_calls_per_turn: int = Field(default=3, ge=1)  # total MCP (code + science)
    tutor_max_code_calls_per_turn: int = Field(default=2, ge=0)  # code subset
    tutor_max_science_calls_per_turn: int = Field(default=3, ge=0)  # science subset
    tutor_max_decision_steps: int = Field(default=8, ge=5)  # raised from 5 to 8
    # Practice coding/science budgets. practice_generation_max_tool_calls is the
    # single per-capability JobToolAuthorization budget (ADR 007 §3.6); the dead
    # practice_coding_max_ref_calls denomination was removed in Slice 5.
    practice_generation_max_tool_calls: int = Field(default=10, ge=0)  # reference + starter validation / science per Set
    practice_grading_max_science_calls: int = Field(default=2, ge=0)  # per scientific item
    # Lesson Writer science budget
    lesson_generation_max_science_calls: int = Field(default=3, ge=0)  # per Lesson Job

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_job_timing(self) -> "Settings":
        if self.ingestion_heartbeat_seconds >= self.ingestion_lease_seconds:
            raise ValueError("INGESTION_HEARTBEAT_SECONDS must be lower than INGESTION_LEASE_SECONDS")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
