"""
Agente Triador - Classifica domínio de incidentes técnicos.

Responsabilidade:
- Lê arquivo limpo (limpo.txt)
- Classifica domínio: Airflow, Kubernetes, Hadoop, Spark, Kafka, etc.
- Define severidade e tags
- Marca como ambíguo se confiança < threshold
- Grava classificação + metadados (S3/DB)

RBAC Role: triador
"""
from .main import TriadorAgent, run_triador

__all__ = ["TriadorAgent", "run_triador"]