"""
Shared Pydantic schemas for inter-agent communication.

All agents use these models for input/output validation.
"""
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Dominio(str, Enum):
    """Domínios técnicos conhecidos para classificação."""
    AIRFLOW = "airflow"
    KUBERNETES = "kubernetes"
    HADOOP = "hadoop"
    SPARK = "spark"
    KAFKA = "kafka"
    DATABASE = "database"
    NETWORK = "network"
    SECURITY = "security"
    UNKNOWN = "unknown"


class Severidade(str, Enum):
    """Severidade do incidente."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class StatusProcessamento(str, Enum):
    """Status do processamento pelo pipeline."""
    PENDING = "pending"
    REDACTED = "redacted"
    CLASSIFIED = "classified"
    ANALYZED = "analyzed"
    HANDOFF_SENT = "handoff_sent"
    FAILED = "failed"


class AgenteRole(str, Enum):
    """Roles RBAC para agentes."""
    REDATOR = "redator"
    TRIADOR = "triador"
    ESPECIALISTA = "especialista"
    HANDOFF = "handoff"


# ===================== Input/Output Models =====================

class BrutoInput(BaseModel):
    """Entrada bruta capturada (log, erro, stacktrace)."""
    conteudo: str
    fonte: str = Field(description="Origem: arquivo, stream, API, etc.")
    timestamp_captura: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class LimpoOutput(BaseModel):
    """Saída do Redator: conteúdo sanitizado."""
    conteudo: str
    redacoes_aplicadas: list[str] = Field(default_factory=list)
    timestamp_redacao: datetime = Field(default_factory=datetime.utcnow)
    agente: Literal[AgenteRole.REDATOR] = AgenteRole.REDATOR


class ClassificacaoOutput(BaseModel):
    """Saída do Triador: classificação de domínio."""
    dominio: Dominio
    confianca: float = Field(ge=0.0, le=1.0, description="0.0 a 1.0")
    severidade: Severidade = Severidade.MEDIUM
    tags: list[str] = Field(default_factory=list)
    ambíguo: bool = Field(default=False, description="Requer especialista?")
    timestamp_classificacao: datetime = Field(default_factory=datetime.utcnow)
    agente: Literal[AgenteRole.TRIADOR] = AgenteRole.TRIADOR
    limpo_id: str | None = Field(None, description="ID do limpo.txt processado")


class AnaliseEspecialistaOutput(BaseModel):
    """Saída do Especialista: causa raiz + solução."""
    causa_raiz: str
    solucao_sugerida: str
    acoes_imediatas: list[str] = Field(default_factory=list)
    acoes_preventivas: list[str] = Field(default_factory=list)
    referencias: list[str] = Field(default_factory=list, description="Links docs, runbooks")
    timestamp_analise: datetime = Field(default_factory=datetime.utcnow)
    agente: Literal[AgenteRole.ESPECIALISTA] = AgenteRole.ESPECIALISTA
    classificacao_id: str | None = None


class HandoffPayload(BaseModel):
    """Payload para envio ao time (Jira, Slack, etc.)."""
    titulo: str
    descricao: str
    dominio: Dominio
    severidade: Severidade
    causa_raiz: str | None = None
    solucao_sugerida: str | None = None
    acoes_imediatas: list[str] = Field(default_factory=list)
    referencias: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    timestamp_handoff: datetime = Field(default_factory=datetime.utcnow)
    agente: Literal[AgenteRole.HANDOFF] = AgenteRole.HANDOFF
    classificacao_id: str | None = None
    analise_id: str | None = None


# ===================== Pipeline Tracking =====================

class PipelineRecord(BaseModel):
    """Registro completo de uma execução do pipeline."""
    pipeline_id: str
    bruto: BrutoInput
    limpo: LimpoOutput | None = None
    classificacao: ClassificacaoOutput | None = None
    analise: AnaliseEspecialistaOutput | None = None
    handoff: HandoffPayload | None = None
    status: StatusProcessamento = StatusProcessamento.PENDING
    erro: str | None = None
    metadata: dict = Field(default_factory=dict)
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    atualizado_em: datetime = Field(default_factory=datetime.utcnow)


# ===================== Config Models =====================

class AgentConfig(BaseModel):
    """Configuração base para qualquer agente."""
    role: AgenteRole
    input_path: str
    output_path: str
    s3_bucket: str | None = None
    loki_url: str | None = None
    kafka_brokers: str | None = None
    log_level: str = "INFO"
    max_retries: int = 3
    timeout_seconds: int = 300


class RedatorConfig(AgentConfig):
    role: Literal[AgenteRole.REDATOR] = AgenteRole.REDATOR
    padroes_customizados: list[str] = Field(default_factory=list)
    usar_trufflehog: bool = False


class TriadorConfig(AgentConfig):
    role: Literal[AgenteRole.TRIADOR] = AgenteRole.TRIADOR
    modelo_classificacao: str = "keyword"  # keyword, ml, llm
    threshold_confianca: float = 0.7


class EspecialistaConfig(AgentConfig):
    role: Literal[AgenteRole.ESPECIALISTA] = AgenteRole.ESPECIALISTA
    usar_llm: bool = True
    modelo_llm: str = "gpt-4"
    base_conhecimento_path: str | None = None


class HandoffConfig(AgentConfig):
    role: Literal[AgenteRole.HANDOFF] = AgenteRole.HANDOFF
    canais: list[Literal["jira", "slack", "email", "teams"]] = Field(default_factory=list)
    jira_project_key: str | None = None
    slack_webhook_url: str | None = None