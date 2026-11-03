"""
Testes para o Agente Triador.
"""
import tempfile
from pathlib import Path

import pytest
from agent_shared.schemas import (
    AgenteRole,
    BrutoInput,
    Dominio,
    LimpoOutput,
    PipelineRecord,
    Severidade,
    StatusProcessamento,
    TriadorConfig,
)
from agent_shared.utils import salvar_json

from triador.main import TriadorAgent, run_triador


class TestTriadorAgent:
    """Testes unitários do TriadorAgent."""

    @pytest.fixture
    def config(self):
        return TriadorConfig(
            role=AgenteRole.TRIADOR,
            input_path="/tmp/limpo.txt",
            output_path="/tmp/classificacao.json",
            modelo_classificacao="keyword",
            threshold_confianca=0.7
        )

    @pytest.fixture
    def agent(self, config):
        return TriadorAgent(config)

    def test_classifica_airflow(self, agent):
        """Testa classificação de erro Airflow."""
        texto = """
        ERROR - TaskInstance failed: dag_id=example_dag task_id=task1
        Scheduler failed to schedule DAG: airflow.cfg configuration error
        CeleryExecutor lost connection to broker
        """
        dominio, confianca, tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.AIRFLOW
        assert confianca > 0.5
        assert any("airflow" in t.lower() or "dag" in t.lower() for t in tags)

    def test_classifica_kubernetes(self, agent):
        """Testa classificação de erro Kubernetes."""
        texto = """
        kubectl get pods -n production
        Error: pod nginx-deployment-abc123 is in CrashLoopBackOff
        kubelet failed to pull image: registry.io/app:v1.2.3
        """
        dominio, confianca, tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.KUBERNETES
        assert confianca > 0.4
        assert any("pod" in t.lower() or "kubelet" in t.lower() or "crashloopbackoff" in t.lower() for t in tags)

    def test_classifica_hadoop(self, agent):
        """Testa classificação de erro Hadoop."""
        texto = """
        NameNode safemode: Not enough replicas for block blk_123
        DataNode registration failed: java.net.ConnectException
        HDFS dfsadmin -report shows 45% missing blocks
        """
        dominio, confianca, _tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.HADOOP
        assert confianca > 0.5

    def test_classifica_spark(self, agent):
        """Testa classificação de erro Spark."""
        texto = """
        SparkException: Job aborted due to stage failure
        Driver lost executor 5: ExecutorLostFailure
        Shuffle fetch failed: Connection reset by peer
        """
        dominio, confianca, _tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.SPARK
        assert confianca > 0.5

    def test_classifica_kafka(self, agent):
        """Testa classificação de erro Kafka."""
        texto = """
        Kafka consumer group rebalance: partition revoked
        Broker 3 not available: LeaderNotAvailableException
        Offset commit failed: OffsetOutOfRangeException
        """
        dominio, confianca, _tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.KAFKA
        assert confianca > 0.5

    def test_classifica_database(self, agent):
        """Testa classificação de erro Database."""
        texto = """
        PostgreSQL: FATAL: remaining connection slots reserved
        MySQL: Deadlock found when trying to get lock
        MongoDB: Cursor not found, query timeout
        """
        dominio, confianca, _tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.DATABASE
        assert confianca > 0.5

    def test_classifica_network(self, agent):
        """Testa classificação de erro Network."""
        texto = """
        Connection refused: connect to host:port
        DNS resolution failed: NXDOMAIN
        TLS handshake timeout: certificate verify failed
        """
        dominio, confianca, _tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.NETWORK
        assert confianca > 0.5

    def test_classifica_security(self, agent):
        """Testa classificação de erro Security."""
        texto = """
        Unauthorized: invalid token
        RBAC: access denied for user
        Certificate expired: x509: certificate has expired
        """
        dominio, confianca, _tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.SECURITY
        assert confianca > 0.5

    def test_unknown_dominio(self, agent):
        """Testa classificação de domínio desconhecido."""
        texto = "Algum erro genérico sem palavras-chave conhecidas"
        dominio, confianca, tags = agent._classificar_keyword(texto)

        assert dominio == Dominio.UNKNOWN
        assert confianca == 0.0
        assert tags == []

    def test_determinar_severidade_critical(self, agent):
        """Testa determinação de severidade critical."""
        texto = "FATAL: Data corruption detected, system panic"
        severidade = agent._determinar_severidade(texto)
        assert severidade == Severidade.CRITICAL

    def test_determinar_severidade_high(self, agent):
        """Testa determinação de severidade high."""
        texto = "ERROR: Connection timeout, task failed"
        severidade = agent._determinar_severidade(texto)
        assert severidade == Severidade.HIGH

    def test_determinar_severidade_medium(self, agent):
        """Testa determinação de severidade medium."""
        texto = "WARN: High latency detected, retrying"
        severidade = agent._determinar_severidade(texto)
        assert severidade == Severidade.MEDIUM

    def test_determinar_severidade_low(self, agent):
        """Testa determinação de severidade low."""
        texto = "INFO: Job completed successfully"
        severidade = agent._determinar_severidade(texto)
        assert severidade == Severidade.LOW

    def test_ambiguo_threshold(self, agent):
        """Testa marcação de ambíguo baseada no threshold."""
        # Texto com poucas keywords -> baixa confiança
        texto = "airflow erro"  # apenas 1 keyword
        _dominio, confianca, _ = agent._classificar_keyword(texto)
        ambíguo = confianca < agent.threshold

        assert ambíguo is True  # threshold default 0.7

    def test_processar_arquivo_limpo(self, agent):
        """Testa processamento completo de arquivo limpo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "limpo.txt"
            conteudo = """
            ERROR - DAG example_dag task task1 failed
            Scheduler heartbeat missed
            CeleryExecutor connection refused to broker
            """
            entrada.write_text(conteudo)

            resultado = agent.processar(entrada)

            assert resultado.dominio == Dominio.AIRFLOW
            assert resultado.confianca > 0.5
            assert resultado.severidade in [Severidade.HIGH, Severidade.CRITICAL]
            assert not resultado.ambíguo or resultado.confianca < 0.7

            # Verifica arquivo de saída
            saida = entrada.with_name("limpo.classificacao.json")
            assert saida.exists()

    def test_processar_record_json(self, agent):
        """Testa processamento de arquivo .record.json do redator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            record_path = Path(tmpdir) / "limpo.record.json"

            # Cria record simulado
            record = PipelineRecord(
                pipeline_id="test-123",
                bruto=BrutoInput(conteudo="original", fonte="test"),
                limpo=LimpoOutput(
                    conteudo="ERROR - DAG example_dag task task1 failed\nScheduler heartbeat missed",
                    redacoes_aplicadas=[]
                ),
                status=StatusProcessamento.REDACTED
            )
            salvar_json(record_path, record)

            resultado = agent.processar(record_path)

            assert resultado.dominio == Dominio.AIRFLOW
            assert resultado.limpo_id == "test-123"

            # Verifica que record foi atualizado
            import json
            with open(record_path) as f:
                updated = json.load(f)
            assert updated["status"] == "classified"
            assert updated["classificacao"] is not None


class TestRunTriador:
    """Testes de integração."""

    def test_run_triador(self):
        """Testa execução via run_triador."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "limpo.txt"
            entrada.write_text("ERROR - DAG failed task instance timeout")

            resultado = run_triador(str(entrada))

            assert resultado.dominio == Dominio.AIRFLOW


if __name__ == "__main__":
    pytest.main([__file__, "-v"])