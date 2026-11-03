"""
Agente Handoff - Implementação principal.

Envia incidentes para:
- Jira (cria issue)
- Slack (posta em canal)
- Email (via SMTP/API)
- Teams (webhook)

Suporta modo mock para desenvolvimento.
"""
import argparse
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from agent_shared.schemas import (
    AgenteRole,
    AnaliseEspecialistaOutput,
    ClassificacaoOutput,
    Dominio,
    HandoffConfig,
    HandoffPayload,
    PipelineRecord,
    Severidade,
    StatusProcessamento,
)
from agent_shared.utils import (
    atualizar_pipeline_record,
    carregar_json,
    salvar_json,
    setup_logging,
)

logger = setup_logging("INFO", "handoff")


class HandoffAgent:
    """Agente responsável por enviar incidentes para times."""

    def __init__(self, config: HandoffConfig):
        self.config = config
        self.canais = config.canais
        self.jira_client = None
        self.slack_client = None

        self._init_clients()

    def _init_clients(self) -> None:
        """Inicializa clientes para canais configurados."""
        # Jira
        if "jira" in self.canais and self.config.jira_project_key:
            try:
                # Configuração via env vars ou config
                import os

                from jira import JIRA
                jira_url = os.getenv("JIRA_URL")
                jira_user = os.getenv("JIRA_USER")
                jira_token = os.getenv("JIRA_TOKEN")
                if jira_url and jira_user and jira_token:
                    self.jira_client = JIRA(server=jira_url, basic_auth=(jira_user, jira_token))
                    logger.info("Jira client inicializado")
            except ImportError:
                logger.warning("jira package não instalado, Jira desabilitado")
            except Exception as e:
                logger.warning(f"Erro ao inicializar Jira: {e}")

        # Slack
        if "slack" in self.canais and self.config.slack_webhook_url:
            try:
                from slack_sdk.webhook import WebhookClient
                self.slack_client = WebhookClient(self.config.slack_webhook_url)
                logger.info("Slack webhook client inicializado")
            except ImportError:
                logger.warning("slack-sdk não instalado, Slack desabilitado")

    def _montar_payload(
        self,
        classificacao: ClassificacaoOutput,
        analise: AnaliseEspecialistaOutput | None = None,
        conteudo_original: str = ""
    ) -> HandoffPayload:
        """Monta payload rico para envio."""
        # Título baseado em domínio e severidade
        emoji_severidade = {
            Severidade.CRITICAL: "🔴",
            Severidade.HIGH: "🟠",
            Severidade.MEDIUM: "🟡",
            Severidade.LOW: "🟢",
            Severidade.INFO: "🔵",
        }
        emoji = emoji_severidade.get(classificacao.severidade, "⚪")

        titulo = f"{emoji} [{classificacao.dominio.value.upper()}] {classificacao.severidade.value.title()}"

        # Descrição rica
        descricao_partes = [
            f"**Domínio:** {classificacao.dominio.value}",
            f"**Severidade:** {classificacao.severidade.value}",
            f"**Confiança:** {classificacao.confianca:.0%}",
            "",
            "**Conteúdo do Incidente:**",
            f"```\n{conteudo_original[:2000]}\n```" if conteudo_original else "*(conteúdo não disponível)*",
        ]

        if analise:
            descricao_partes.extend([
                "",
                "**Análise do Especialista:**",
                f"**Causa Raiz:** {analise.causa_raiz}",
                f"**Solução Sugerida:** {analise.solucao_sugerida}",
            ])
            if analise.acoes_imediatas:
                descricao_partes.append("**Ações Imediatas:**")
                for acao in analise.acoes_imediatas:
                    descricao_partes.append(f"- {acao}")
            if analise.referencias:
                descricao_partes.append("**Referências/Runbooks:**")
                for ref in analise.referencias:
                    descricao_partes.append(f"- {ref}")

        descricao = "\n".join(descricao_partes)

        # Labels para Jira
        labels = [
            f"dominio:{classificacao.dominio.value}",
            f"severidade:{classificacao.severidade.value}",
            "auto-triado",
        ]
        labels.extend(classificacao.tags)

        # Assignees baseados no domínio (mock)
        assignees_map = {
            Dominio.AIRFLOW: ["team-data-engineering"],
            Dominio.KUBERNETES: ["team-platform", "team-sre"],
            Dominio.HADOOP: ["team-data-engineering", "team-platform"],
            Dominio.SPARK: ["team-data-engineering"],
            Dominio.KAFKA: ["team-platform", "team-data-engineering"],
            Dominio.DATABASE: ["team-dba", "team-platform"],
            Dominio.NETWORK: ["team-network", "team-sre"],
            Dominio.SECURITY: ["team-security", "team-sre"],
        }
        assignees = assignees_map.get(classificacao.dominio, ["team-oncall"])

        return HandoffPayload(
            titulo=titulo,
            descricao=descricao,
            dominio=classificacao.dominio,
            severidade=classificacao.severidade,
            causa_raiz=analise.causa_raiz if analise else None,
            solucao_sugerida=analise.solucao_sugerida if analise else None,
            acoes_imediatas=analise.acoes_imediatas if analise else [],
            labels=labels,
            assignees=assignees,
            classificacao_id=getattr(classificacao, "limpo_id", None),
            analise_id=getattr(analise, "classificacao_id", None) if analise else None,
        )

    def _enviar_jira(self, payload: HandoffPayload) -> dict:
        """Envia para Jira."""
        if not self.jira_client:
            return {"status": "skipped", "reason": "Jira client não configurado"}

        try:
            issue_dict = {
                "project": {"key": self.config.jira_project_key},
                "summary": payload.titulo,
                "description": payload.descricao,
                "issuetype": {"name": "Task"},
                "labels": payload.labels,
            }

            # Adiciona assignee se usuário existir
            if payload.assignees:
                issue_dict["assignee": {"name": payload.assignees[0]}]

            issue = self.jira_client.create_issue(fields=issue_dict)
            logger.info(f"Jira issue criado: {issue.key}")

            return {"status": "success", "issue_key": issue.key, "url": f"{self.jira_client.server_url}/browse/{issue.key}"}
        except Exception as e:
            logger.error(f"Erro ao criar Jira issue: {e}")
            return {"status": "error", "error": str(e)}

    def _enviar_slack(self, payload: HandoffPayload) -> dict:
        """Envia para Slack via webhook."""
        if not self.slack_client:
            return {"status": "skipped", "reason": "Slack webhook não configurado"}

        try:
            # Formata para Slack Block Kit
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": payload.titulo}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": payload.descricao[:3000]}
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Domínio: {payload.dominio.value} | Severidade: {payload.severidade.value}"}
                    ]
                }
            ]

            response = self.slack_client.send(blocks=blocks)
            if response.status_code == 200:
                logger.info("Mensagem Slack enviada")
                return {"status": "success"}
            else:
                logger.error(f"Erro Slack: {response.status_code} - {response.body}")
                return {"status": "error", "error": response.body}
        except Exception as e:
            logger.error(f"Erro ao enviar Slack: {e}")
            return {"status": "error", "error": str(e)}

    def _enviar_email(self, payload: HandoffPayload) -> dict:
        """Envia por email (SMTP)."""
        import os
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASS")
        email_from = os.getenv("EMAIL_FROM")
        email_to = os.getenv("EMAIL_TO", "").split(",")

        if not all([smtp_host, smtp_user, smtp_pass, email_from, email_to]):
            return {"status": "skipped", "reason": "Config SMTP incompleta"}

        try:
            msg = MIMEMultipart()
            msg["From"] = email_from
            msg["To"] = ", ".join(email_to)
            msg["Subject"] = payload.titulo

            # HTML body
            html = f"""
            <html>
            <body>
                <h2>{payload.titulo}</h2>
                <pre>{payload.descricao}</pre>
                <hr>
                <p><small>Automatizado pelo Agent Handoff</small></p>
            </body>
            </html>
            """
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            logger.info(f"Email enviado para {email_to}")
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Erro ao enviar email: {e}")
            return {"status": "error", "error": str(e)}

    def _enviar_teams(self, payload: HandoffPayload) -> dict:
        """Envia para Teams via webhook."""
        import os

        import requests
        teams_webhook = os.getenv("TEAMS_WEBHOOK_URL")

        if not teams_webhook:
            return {"status": "skipped", "reason": "Teams webhook não configurado"}

        try:
            card = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "themeColor": {
                    Severidade.CRITICAL: "FF0000",
                    Severidade.HIGH: "FF8C00",
                    Severidade.MEDIUM: "FFD700",
                    Severidade.LOW: "32CD32",
                    Severidade.INFO: "1E90FF",
                }.get(payload.severidade, "808080"),
                "summary": payload.titulo,
                "sections": [{
                    "activityTitle": payload.titulo,
                    "text": payload.descricao[:3000],
                    "facts": [
                        {"name": "Domínio", "value": payload.dominio.value},
                        {"name": "Severidade", "value": payload.severidade.value},
                    ],
                }]
            }

            response = requests.post(teams_webhook, json=card, timeout=10)
            response.raise_for_status()
            logger.info("Mensagem Teams enviada")
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Erro ao enviar Teams: {e}")
            return {"status": "error", "error": str(e)}

    def processar(
        self,
        arquivo_classificacao: str | Path,
        arquivo_analise: str | Path | None = None
    ) -> dict:
        """
        Processa classificação (+ análise opcional) e envia para canais.

        Args:
            arquivo_classificacao: .classificacao.json ou .record.json
            arquivo_analise: .analise.json (opcional)

        Returns:
            Dict com resultados por canal
        """
        entrada_path = Path(arquivo_classificacao)
        analise_path = Path(arquivo_analise) if arquivo_analise else None

        logger.info(f"Iniciando handoff: {entrada_path}")

        # Carrega classificação e conteúdo
        if entrada_path.suffix == ".json":
            try:
                record = carregar_json(entrada_path, PipelineRecord)
                classificacao = record.classificacao
                conteudo = record.limpo.conteudo if record.limpo else record.bruto.conteudo
                pipeline_id = record.pipeline_id
            except Exception:
                classificacao = carregar_json(entrada_path, ClassificacaoOutput)
                conteudo = ""
                pipeline_id = classificacao.limpo_id
        else:
            raise ValueError("Arquivo deve ser .json")

        # Carrega análise se existir
        analise = None
        if analise_path and analise_path.exists():
            analise = carregar_json(analise_path, AnaliseEspecialistaOutput)
        elif 'record' in locals() and record and record.analise:
            analise = record.analise

        # Monta payload
        payload = self._montar_payload(classificacao, analise, conteudo)

        # Salva payload para auditoria
        payload_path = entrada_path.with_name(f"{entrada_path.stem}.handoff.json")
        salvar_json(payload_path, payload)

        # Envia para cada canal
        resultados = {}
        for canal in self.canais:
            logger.info(f"Enviando para {canal}...")
            if canal == "jira":
                resultados["jira"] = self._enviar_jira(payload)
            elif canal == "slack":
                resultados["slack"] = self._enviar_slack(payload)
            elif canal == "email":
                resultados["email"] = self._enviar_email(payload)
            elif canal == "teams":
                resultados["teams"] = self._enviar_teams(payload)
            else:
                resultados[canal] = {"status": "skipped", "reason": "Canal não suportado"}

        # Log resumo
        sucessos = [k for k, v in resultados.items() if v.get("status") == "success"]
        logger.info(f"Handoff concluído: {len(sucessos)}/{len(resultados)} canais com sucesso")

        # Atualiza record se existir
        if 'record' in locals() and record:
            record = atualizar_pipeline_record(
                record,
                StatusProcessamento.HANDOFF_SENT,
                handoff=payload
            )
            record.metadata = record.metadata or {}
            record.metadata["handoff_resultados"] = resultados
            salvar_json(entrada_path, record)

        return resultados


def run_handoff(
    arquivo_classificacao: str,
    arquivo_analise: str | None = None,
    config: HandoffConfig | None = None
) -> dict:
    """Função de conveniência para executar o handoff."""
    if config is None:
        config = HandoffConfig(
            role=AgenteRole.HANDOFF,
            input_path=arquivo_classificacao,
            output_path=arquivo_classificacao.replace(".json", ".handoff.json"),
            canais=["slack"]  # Default
        )

    agent = HandoffAgent(config)
    return agent.processar(arquivo_classificacao, arquivo_analise)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Agente Handoff - Envia incidentes para times")
    parser.add_argument("classificacao", help="Arquivo de classificação (.classificacao.json ou .record.json)")
    parser.add_argument("--analise", help="Arquivo de análise (.analise.json)")
    parser.add_argument("--config", help="Arquivo de configuração JSON")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--canais", nargs="+", choices=["jira", "slack", "email", "teams"],
                        default=["slack"], help="Canais para envio")

    args = parser.parse_args()

    global logger
    logger = setup_logging(args.log_level, "handoff")

    config = None
    if args.config:
        import json
        with open(args.config) as f:
            config_data = json.load(f)
        config = HandoffConfig(**config_data)
    else:
        config = HandoffConfig(
            role=AgenteRole.HANDOFF,
            input_path=args.classificacao,
            output_path=args.classificacao.replace(".json", ".handoff.json"),
            canais=args.canais,
            log_level=args.log_level
        )

    try:
        resultados = run_handoff(args.classificacao, args.analise, config)
        print("✅ Handoff concluído")
        for canal, resultado in resultados.items():
            status = resultado.get("status", "unknown")
            icon = "✅" if status == "success" else "⏭️" if status == "skipped" else "❌"
            print(f"  {icon} {canal}: {status}")
            if status == "error":
                print(f"     Erro: {resultado.get('error')}")
        return 0 if any(r.get("status") == "success" for r in resultados.values()) else 1
    except Exception as e:
        logger.error(f"Falha no handoff: {e}")
        print(f"❌ Erro: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())