"""
Agente Handoff - Envia incidentes classificados para times.

Responsabilidade:
- Recebe classificação + análise (opcional)
- Monta payload rico (título, descrição, severidade, ações)
- Envia para canais configurados: Jira, Slack, Email, Teams
- Registra handoff para auditoria

RBAC Role: handoff
"""
from .main import HandoffAgent, run_handoff

__all__ = ["HandoffAgent", "run_handoff"]