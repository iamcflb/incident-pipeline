"""
Shared utilities for all agents.
"""
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .schemas import PipelineRecord, StatusProcessamento

# Counter para garantir IDs únicos em testes rápidos
_pipeline_id_counter = 0


def setup_logging(level: str = "INFO", agent_name: str = "agent") -> logging.Logger:
    """Configura logging estruturado JSON para Loki."""
    logger = logging.getLogger(agent_name)
    logger.setLevel(getattr(logging, level.upper()))

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"agent": "%(name)s", "message": "%(message)s"}'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def gerar_pipeline_id(conteudo: str) -> str:
    """Gera ID único para o pipeline baseado no hash do conteúdo + timestamp + counter."""
    global _pipeline_id_counter
    _pipeline_id_counter += 1
    hash_curto = hashlib.sha256(conteudo.encode()).hexdigest()[:12]
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")[:-3]  # milissegundos
    return f"pipe-{timestamp}-{hash_curto}-{_pipeline_id_counter:04d}"


def salvar_json(caminho: str | Path, dados: dict | BaseModel) -> None:
    """Salva dados como JSON formatado."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(dados, "model_dump"):
        dados = dados.model_dump(mode="json")

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, default=str)


def carregar_json(caminho: str | Path, modelo: type | None = None) -> Any:
    """Carrega JSON e opcionalmente valida com Pydantic."""
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    if modelo and hasattr(modelo, "model_validate"):
        return modelo.model_validate(dados)
    return dados


def atualizar_pipeline_record(
    record: PipelineRecord,
    status: StatusProcessamento,
    **campos: Any
) -> PipelineRecord:
    """Atualiza um PipelineRecord com novo status e campos."""
    record.status = status
    record.atualizado_em = datetime.now(UTC)
    for k, v in campos.items():
        if hasattr(record, k):
            setattr(record, k, v)
    return record


# ===================== Redaction Patterns =====================

# Ordem importa: patterns mais específicos primeiro
PADROES_SENSIVEIS_DEFAULT = [
    # JWT (deve vir antes de token genérico) - matcha JWT puro ou prefixado
    (r"(?i)(?:token\s*[:=]\s*)?(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", "jwt"),
    # Senhas
    (r"(?i)(senha|password|pwd|pass)\s*[:=]\s*[^\s]+", "senha"),
    # Tokens específicos (access_token, refresh_token, api_key, apikey)
    (r"(?i)(access_token|refresh_token|api_key|apikey)\s*[:=]\s*[^\s]+", "token"),
    # Token genérico (não JWT)
    (r"(?i)token\s*[:=]\s*(?![A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\.)[^\s]+", "token"),
    # Secrets
    (r"(?i)(secret|client_secret)\s*[:=]\s*[^\s]+", "secret"),
    # Keytab / Kerberos
    (r"(?i)keytab\s*[:=]\s*[^\s]+", "keytab"),
    # AWS
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"(?i)aws_secret_access_key\s*[:=]\s*[^\s]+", "aws_secret"),
    # Database URLs
    (r"(?i)(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@", "db_url"),
    # Generic key=value patterns
    (r"(?i)(private_key|ssh_key|cert)\s*[:=]\s*[^\s]+", "private_key"),
]


def compilar_padroes(padroes_customizados: list[str] | None = None) -> list[tuple[re.Pattern, str]]:
    """Compila regex patterns para redação."""
    padroes = [(re.compile(p, re.IGNORECASE), label) for p, label in PADROES_SENSIVEIS_DEFAULT]

    if padroes_customizados:
        for p in padroes_customizados:
            try:
                padroes.append((re.compile(p, re.IGNORECASE), "custom"))
            except re.error:
                pass  # Ignora patterns inválidos

    return padroes


def redatar_texto(texto: str, padroes: list[tuple[re.Pattern, str]] | None = None) -> tuple[str, list[str]]:
    """
    Remove dados sensíveis do texto.

    Returns:
        tuple: (texto_redatado, lista_de_labels_redatados)
    """
    if padroes is None:
        padroes = compilar_padroes()

    redacoes = []
    resultado = texto

    for pattern, label in padroes:
        matches = pattern.findall(resultado)
        if matches:
            # Se o pattern tem grupos, findall retorna tuplas; pega o grupo relevante
            if matches and isinstance(matches[0], tuple):
                # Para JWT, o grupo 1 é o token JWT
                redacoes.extend([label] * len(matches))
            else:
                redacoes.extend([label] * len(matches))
            resultado = pattern.sub(f"[REDACTED:{label.upper()}]", resultado)

    return resultado, redacoes