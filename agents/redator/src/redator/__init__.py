"""
Agente Redator - Remove dados sensíveis de arquivos de log/erro.

Responsabilidade:
- Lê arquivo bruto (bruto.txt)
- Remove senhas, tokens, keytabs, JWTs, chaves AWS, URLs de DB, etc.
- Grava arquivo limpo (limpo.txt)
- Registra metadados de redação para auditoria

RBAC Role: redator
"""
from .main import RedatorAgent, run_redator

__all__ = ["RedatorAgent", "run_redator"]