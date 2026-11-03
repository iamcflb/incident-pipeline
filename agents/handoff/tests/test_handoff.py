"""
Testes para o Agente Handoff.
"""
import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from handoff.main import HandoffAgent, run_handoff
from agent_shared.schemas import (
    HandoffConfig,
    AgenteRole,
    ClassificacaoOutput,
    AnaliseEspecialistaOutput,
    Dominio,
    Severidade,
    PipelineRecord,
    StatusProcessamento,
    LimpoOutput,
)
from agent_shared.utils import salvar_json


class TestHandoffAgent:
    """Testes unitários do HandoffAgent."""

    @pytest.fixture
    def config(self):
        return HandoffConfig(
            role=AgenteRole.HANDOFF,
            input_path="/tmp/classificacao.json",
            output_path="/tmp/handoff.json",
            canais=["slack", "jira"],  # Serão mockados
            slack_webhook_url="https://hooks.slack.com/test",
            jira_project_key="INC"
        )

    @pytest.fixture
    def agent(self, config):
        with patch("handoff.main.JIRA"), patch("handoff.main.WebhookClient"):
            return HandoffAgent(config)

    def test_montar_payload_basico(self, agent):
        """Testa montagem de payload básico."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.AIRFLOW,
            confianca=0.9,
            severidade=Severidade.HIGH,
            tags=["dag", "scheduler"],
            limpo_id="test-123"
        )
        conteudo = "ERROR - DAG failed: scheduler heartbeat missed"

        payload = agent._montar_payload(classificacao, None, conteudo)

        assert "AIRFLOW" in payload.titulo
        assert "HIGH" in payload.titulo
        assert payload.dominio == Dominio.AIRFLOW
        assert payload.severidade == Severidade.HIGH
        assert "dag" in payload.labels
        assert "scheduler" in payload.labels
        assert "team-data-engineering" in payload.assignees

    def test_montar_payload_com_analise(self, agent):
        """Testa montagem de payload com análise do especialista."""
        classificacao = ClassificacaoOutput(
            dominio=Dominio.KUBERNETES,
            confianca=0.6,
            severidade=Severidade.CRITICAL,
            ambíguo=True,
            tags=["pod", "oomkilled"],
            limpo_id="test-456"
        )
        analise = AnaliseEspecialistaOutput(
            causa_raiz="OOMKilled: container excedeu memory limit",
            solucao_sugerida="Aumentar memory limit no deployment",
            acoes_imediatas=[
                "kubectl describe pod",
                "Aumentar limits.memory",
                "Reiniciar deployment"
            ],
            referencias=["https://runbooks.interno/k8s-oomkilled"],
            classificacao_id="test-456"
        )
        conteudo = "Pod nginx-abc123 OOMKilled"

        payload = agent._montar_payload(classificacao, analise, conteudo)

        assert "OOMKilled" in payload.causa_raiz
        assert "memory limit" in payload.solucao_sugerida
        assert len(payload.acoes_imediatas) == 3
        assert len(payload.referencias) == 1

    def test_emoji_severidade(self, agent):
        """Testa emojis de severidade no título."""
        for severidade, emoji in [
            (Severidade.CRITICAL, "🔴"),
            (Severidade.HIGH, "🟠"),
            (Severidade.MEDIUM, "🟡"),
            (Severidade.LOW, "🟢"),
            (Severidade.INFO, "🔵"),
        ]:
            classificacao = ClassificacaoOutput(
                dominio=Dominio.AIRFLOW,
                confianca=0.9,
                severidade=severidade,
                limpo_id="test"
            )
            payload = agent._montar_payload(classificacao, None, "")
            assert emoji in payload.titulo

    @patch("handoff.main.WebhookClient")
    def test_enviar_slack_sucesso(self, mock_webhook_class, agent):
        """Testa envio bem-sucedido para Slack."""
        mock_webhook = Mock()
        mock_webhook.send.return_value = Mock(status_code=200)
        mock_webhook_class.return_value = mock_webhook

        # Recria agent com mock
        agent.slack_client = mock_webhook

        payload = agent._montar_payload(
            ClassificacaoOutput(dominio=Dominio.AIRFLOW, confianca=0.9, severidade=Severidade.HIGH, limpo_id="t"),
            None, "conteúdo"
        )

        resultado = agent._enviar_slack(payload)

        assert resultado["status"] == "success"
        mock_webhook.send.assert_called_once()

    @patch("handoff.main.WebhookClient")
    def test_enviar_slack_falha(self, mock_webhook_class, agent):
        """Testa falha no envio para Slack."""
        mock_webhook = Mock()
        mock_webhook.send.return_value = Mock(status_code=500, body="Internal Error")
        mock_webhook_class.return_value = mock_webhook
        agent.slack_client = mock_webhook

        payload = agent._montar_payload(
            ClassificacaoOutput(dominio=Dominio.AIRFLOW, confianca=0.9, severidade=Severidade.HIGH, limpo_id="t"),
            None, "conteúdo"
        )

        resultado = agent._enviar_slack(payload)

        assert resultado["status"] == "error"

    def test_enviar_jira_sem_client(self, agent):
        """Testa Jira pulado quando client não configurado."""
        agent.jira_client = None

        payload = agent._montar_payload(
            ClassificacaoOutput(dominio=Dominio.AIRFLOW, confianca=0.9, severidade=Severidade.HIGH, limpo_id="t"),
            None, "conteúdo"
        )

        resultado = agent._enviar_jira(payload)

        assert resultado["status"] == "skipped"

    def test_enviar_email_sem_config(self, agent):
        """Testa email pulado quando config incompleta."""
        payload = agent._montar_payload(
            ClassificacaoOutput(dominio=Dominio.AIRFLOW, confianca=0.9, severidade=Severidade.HIGH, limpo_id="t"),
            None, "conteúdo"
        )

        resultado = agent._enviar_email(payload)

        assert resultado["status"] == "skipped"

    def test_processar_classificacao_json(self, agent):
        """Testa processamento completo com arquivo .classificacao.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "classificacao.json"

            classificacao = ClassificacaoOutput(
                dominio=Dominio.AIRFLOW,
                confianca=0.9,
                severidade=Severidade.HIGH,
                tags=["dag"],
                limpo_id="pipe-123"
            )
            salvar_json(entrada, classificacao)

            # Mock canais para não fazer chamadas reais
            agent._enviar_slack = Mock(return_value={"status": "success"})
            agent._enviar_jira = Mock(return_value={"status": "skipped", "reason": "no client"})

            resultados = agent.processar(entrada)

            assert "slack" in resultados
            assert resultados["slack"]["status"] == "success"

            # Verifica arquivo handoff salvo
            saida = entrada.with_name("classificacao.handoff.json")
            assert saida.exists()

    def test_processar_record_json(self, agent):
        """Testa processamento com arquivo .record.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            record_path = Path(tmpdir) / "limpo.record.json"

            record = PipelineRecord(
                pipeline_id="pipe-789",
                bruto=None,
                limpo=LimpoOutput(
                    conteudo="ERROR - DAG scheduler failed",
                    redacoes_aplicadas=[]
                ),
                classificacao=ClassificacaoOutput(
                    dominio=Dominio.AIRFLOW,
                    confianca=0.9,
                    severidade=Severidade.HIGH,
                    tags=["scheduler"],
                    limpo_id="pipe-789"
                ),
                status=StatusProcessamento.CLASSIFIED
            )
            salvar_json(record_path, record)

            agent._enviar_slack = Mock(return_value={"status": "success"})

            resultados = agent.processar(record_path)

            assert resultados["slack"]["status"] == "success"

            # Verifica record atualizado
            import json
            with open(record_path) as f:
                updated = json.load(f)
            assert updated["status"] == "handoff_sent"
            assert updated["handoff"] is not None
            assert "handoff_resultados" in updated.get("metadata", {})


class TestRunHandoff:
    """Testes de integração."""

    def test_run_handoff_mock(self):
        """Testa execução via run_handoff com mocks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "classificacao.json"

            classificacao = ClassificacaoOutput(
                dominio=Dominio.KUBERNETES,
                confianca=0.8,
                severidade=Severidade.CRITICAL,
                tags=["pod", "crashloop"],
                limpo_id="test-run"
            )
            salvar_json(entrada, classificacao)

            config = HandoffConfig(
                role=AgenteRole.HANDOFF,
                input_path=str(entrada),
                output_path=str(entrada.with_name("handoff.json")),
                canais=["slack"],
                slack_webhook_url="https://hooks.slack.com/test"
            )

            with patch("handoff.main.WebhookClient") as mock_webhook_class:
                mock_webhook = Mock()
                mock_webhook.send.return_value = Mock(status_code=200)
                mock_webhook_class.return_value = mock_webhook

                resultados = run_handoff(str(entrada), config=config)

                assert resultados["slack"]["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])