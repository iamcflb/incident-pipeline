"""
Agente Especialista - Análise profunda de incidentes ambíguos.

Responsabilidade:
- Recebe classificações marcadas como ambíguas
- Analisa causa raiz usando LLM + base de conhecimento
- Sugere solução imediata e preventiva
- Fornece referências (runbooks, docs, tickets anteriores)

RBAC Role: especialista
"""
from .main import EspecialistaAgent, run_especialista

__all__ = ["EspecialistaAgent", "run_especialista"]