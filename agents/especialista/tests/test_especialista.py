"""
Testes para o Agente Especialista.
"""
import tempfile
from pathlib import Path

import pytest
from agent_shared.schemas import (
    AgenteRole,
    BrutoInput,
    ClassificacaoOutput,
    Dominio,
    EspecialistaConfig,
    LimpoOutput,
    PipelineRecord,
    Severidade,
    StatusProcessamento,
)
from agent_shared.utils import salvar_json

from especialista.main import EspecialistaAgent, run_especialista


class TestEspecialistaAgent:
    """Testes unitários do EspecialistaAgent."""

    @pytest.fixture
    def config(self):
        return EspecialistaConfig(
            role=AgenteRole.ESPECIALISTA,
            input_path="/tmp/classificacao.json",
            output_path="/tmp/analise.json",
            usar_llm=False  # Usa mock
        )

    @pytest.fixture
    def agent(self, config):
        return EspecialistaAgent(config)

    def test_base_conhecimento_carregada(self, agent):
        """Testa se base de conhecimento tem todos os domínios."""
        for dominio in Dominio:
            if dominio != Dominio.UNKNOWN:
                assert dominio in agent.base_conhecimento
                kb = agent.base_conhecimento[dominio]
                assert "causas_comuns" in kb
                assert "solucoes" in kb
                assert "runbooks" in kb
                assert len(kb["causas_comuns"]) > 0
                assert len(kb["solucoes"]) > 0

    def test_analisar_mock_airflow(self, agent):
        """Testa análise mock para Airflow."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.AIRFLOW,
            confianca=0.5,
            severidade=Severidade.HIGH,
            ambíguo=True,
            tags=["dag", "scheduler"],
            limpo_id="test-123"
        )
        conteudo = "ERROR - Scheduler failed to schedule DAG: metadata database connection failed"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "scheduler" in resultado.causa_raiz.lower() or "database" in resultado.causa_raiz.lower()
        assert len(resultado.acoes_imediatas) > 0
        assert len(resultado.referencias) > 0
        assert resultado.classificacao_id == "test-123"

    def test_analisar_mock_kubernetes(self, agent):
        """Testa análise mock para Kubernetes."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.KUBERNETES,
            confianca=0.4,
            severidade=Severidade.CRITICAL,
            ambíguo=True,
            tags=["pod", "oomkilled"],
            limpo_id="test-456"
        )
        conteudo = "Pod nginx-deployment-abc123 is in CrashLoopBackOff: OOMKilled"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "oom" in resultado.causa_raiz.lower() or "crashloop" in resultado.causa_raiz.lower()
        assert len(resultado.acoes_imediatas) > 0

    def test_analisar_mock_hadoop(self, agent):
        """Testa análise mock para Hadoop."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.HADOOP,
            confianca=0.6,
            severidade=Severidade.HIGH,
            ambíguo=True,
            tags=["namenode", "safemode"],
            limpo_id="test-789"
        )
        conteudo = "NameNode entered safemode: not enough replicas for blocks"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "safemode" in resultado.causa_raiz.lower() or "replica" in resultado.causa_raiz.lower()

    def test_analisar_mock_spark(self, agent):
        """Testa análise mock para Spark."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.SPARK,
            confianca=0.5,
            severidade=Severidade.HIGH,
            ambíguo=True,
            tags=["oom", "executor"],
            limpo_id="test-spark"
        )
        conteudo = "ExecutorLostFailure: Container killed by YARN for exceeding memory limits"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "oom" in resultado.causa_raiz.lower() or "memory" in resultado.causa_raiz.lower()

    def test_analisar_mock_kafka(self, agent):
        """Testa análise mock para Kafka."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.KAFKA,
            confianca=0.5,
            severidade=Severidade.MEDIUM,
            ambíguo=True,
            tags=["consumer", "lag"],
            limpo_id="test-kafka"
        )
        conteudo = "Consumer group lag increasing: partition 0 lag 10000"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "lag" in resultado.causa_raiz.lower() or "consumer" in resultado.causa_raiz.lower()

    def test_analisar_mock_database(self, agent):
        """Testa análise mock para Database."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.DATABASE,
            confianca=0.6,
            severidade=Severidade.HIGH,
            ambíguo=True,
            tags=["deadlock", "postgresql"],
            limpo_id="test-db"
        )
        conteudo = "Deadlock detected: Process 123 waits for ShareLock on transaction 456"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "deadlock" in resultado.causa_raiz.lower() or "lock" in resultado.causa_raiz.lower()

    def test_analisar_mock_network(self, agent):
        """Testa análise mock para Network."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.NETWORK,
            confianca=0.5,
            severidade=Severidade.MEDIUM,
            ambíguo=True,
            tags=["dns", "timeout"],
            limpo_id="test-net"
        )
        conteudo = "DNS resolution failed: NXDOMAIN for service.internal"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "dns" in resultado.causa_raiz.lower()

    def test_analisar_mock_security(self, agent):
        """Testa análise mock para Security."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.SECURITY,
            confianca=0.7,
            severidade=Severidade.HIGH,
            ambíguo=True,
            tags=["rbac", "forbidden"],
            limpo_id="test-sec"
        )
        conteudo = "RBAC: access denied for user service-account in namespace prod"

        resultado = agent._analisar_mock(classificacao, conteudo)

        assert "rbac" in resultado.causa_raiz.lower() or "access denied" in resultado.causa_raiz.lower()

    def test_nao_ambiguo_retorna_direto(self, agent):
        """Testa que classificação não ambígua retorna direto via processar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "classificacao.json"

            classificacao = ClassificacaoOutput(
                dominio=Dominio.AIRFLOW,
                confianca=0.9,
                severidade=Severidade.HIGH,
                ambíguo=False,
                tags=["dag"],
                limpo_id="test-clear"
            )
            salvar_json(entrada, classificacao)

            resultado = agent.processar(entrada)

            assert "não requer análise profunda" in resultado.causa_raiz
            assert "handoff direto" in resultado.solucao_sugerida

    def test_processar_classificacao_json(self, agent):
        """Testa processamento de arquivo .classificacao.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "classificacao.json"

            classificacao = ClassificacaoOutput(
                dominio=Dominio.AIRFLOW,
                confianca=0.5,
                severidade=Severidade.HIGH,
                ambíguo=True,
                tags=["scheduler", "database"],
                limpo_id="pipe-123"
            )
            salvar_json(entrada, classificacao)

            resultado = agent.processar(entrada)

            assert resultado.causa_raiz
            assert resultado.solucao_sugerida
            assert len(resultado.acoes_imediatas) > 0

            # Verifica arquivo de saída
            saida = entrada.with_name("classificacao.analise.json")
            assert saida.exists()

    def test_processar_record_json(self, agent):
        """Testa processamento de arquivo .record.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            record_path = Path(tmpdir) / "limpo.record.json"

            # Cria record simulado
            record = PipelineRecord(
                pipeline_id="pipe-456",
                bruto=BrutoInput(conteudo="original", fonte="test"),
                limpo=LimpoOutput(
                    conteudo="ERROR - Scheduler heartbeat missed, database connection failed",
                    redacoes_aplicadas=[]
                ),
                classificacao=ClassificacaoOutput(
                    dominio=Dominio.AIRFLOW,
                    confianca=0.4,
                    severidade=Severidade.HIGH,
                    ambíguo=True,
                    tags=["scheduler", "heartbeat"],
                    limpo_id="pipe-456"
                ),
                status=StatusProcessamento.CLASSIFIED
            )
            salvar_json(record_path, record)

            resultado = agent.processar(record_path)

            assert resultado.classificacao_id == "pipe-456"

            # Verifica record atualizado
            import json
            with open(record_path) as f:
                updated = json.load(f)
            assert updated["status"] == "analyzed"
            assert updated["analise"] is not None


class TestRunEspecialista:
    """Testes de integração."""

    def test_run_especialista(self):
        """Testa execução via run_especialista."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "classificacao.json"

            classificacao = ClassificacaoOutput(
                dominio=Dominio.KUBERNETES,
                confianca=0.5,
                severidade=Severidade.CRITICAL,
                ambíguo=True,
                tags=["pod", "oomkilled"],
                limpo_id="test-run"
            )
            salvar_json(entrada, classificacao)

            resultado = run_especialista(str(entrada))

            assert "oom" in resultado.causa_raiz.lower() or "crashloop" in resultado.causa_raiz.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])