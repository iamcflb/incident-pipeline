"""
Agente Especialista - Implementação principal.

Analisa incidentes ambíguos usando:
1. LLM (OpenAI/Anthropic) para análise de causa raiz
2. Base de conhecimento local (runbooks, docs, tickets históricos)
3. Heurísticas baseadas em domínio

Pode rodar em modo "mock" para desenvolvimento sem API keys.
"""
import argparse
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from agent_shared.schemas import (
    ClassificacaoOutput,
    AnaliseEspecialistaOutput,
    PipelineRecord,
    StatusProcessamento,
    EspecialistaConfig,
    AgenteRole,
    Dominio,
)
from agent_shared.utils import (
    setup_logging,
    gerar_pipeline_id,
    salvar_json,
    carregar_json,
    atualizar_pipeline_record,
)

logger = setup_logging("INFO", "especialista")


# ===================== Base de Conhecimento Mock =====================

BASE_CONHECIMENTO = {
    Dominio.AIRFLOW: {
        "causas_comuns": [
            "Scheduler parado ou sem recursos",
            "Database metadata indisponível",
            "DAG com dependência circular",
            "Executor sem workers disponíveis",
            "XCom muito grande (memory error)",
        ],
        "solucoes": [
            "Reiniciar scheduler/webserver",
            "Verificar conexão DB metadata",
            "Corrigir DAG (remover ciclo)",
            "Escalar workers Celery/K8s",
            "Usar XCom backend externo (S3/GCS)",
        ],
        "runbooks": [
            "https://runbooks.interno/airflow-scheduler-down",
            "https://runbooks.interno/airflow-db-connection",
            "https://runbooks.interno/airflow-xcom-oom",
        ],
    },
    Dominio.KUBERNETES: {
        "causas_comuns": [
            "Pod em CrashLoopBackOff (OOMKilled, erro app)",
            "Node pressure (memory/disk/pid)",
            "ImagePullBackOff (registry auth, imagem inexistente)",
            "Pending pod (recursos insuficientes, taints)",
            "CNI/CSI issues (rede/storage não funciona)",
        ],
        "solucoes": [
            "kubectl describe pod + logs anterior",
            "kubectl top nodes, verificar taints",
            "Verificar secret registry, image tag",
            "Escalar cluster ou ajustar requests/limits",
            "Verificar pods CNI/CSI, reiniciar daemonset",
        ],
        "runbooks": [
            "https://runbooks.interno/k8s-crashloopbackoff",
            "https://runbooks.interno/k8s-node-pressure",
            "https://runbooks.interno/k8s-imagepullbackoff",
            "https://runbooks.interno/k8s-pending-pods",
        ],
    },
    Dominio.HADOOP: {
        "causas_comuns": [
            "NameNode em SafeMode (blocos sub-replicados)",
            "DataNode desconectado (rede, disco cheio)",
            "YARN ApplicationMaster falhou",
            "Hive metastore indisponível",
            "ZooKeeper quorum perdido",
        ],
        "solucoes": [
            "hdfs dfsadmin -safemode leave",
            "Verificar logs DataNode, espaço em disco",
            "Reiniciar RM/NM, verificar container logs",
            "Reiniciar Hive Metastore, verificar DB backend",
            "Verificar ensemble ZK, reiniciar nós",
        ],
        "runbooks": [
            "https://runbooks.interno/hadoop-namenode-safemode",
            "https://runbooks.interno/hadoop-datanode-down",
            "https://runbooks.interno/hadoop-yarn-am-fail",
        ],
    },
    Dominio.SPARK: {
        "causas_comuns": [
            "OOM no Driver/Executor (memória insuficiente)",
            "Shuffle spill (dados não cabem em memória)",
            "Data skew (partição muito grande)",
            "Executor lost (OOM, YARN kill, rede)",
            "Serialização (Kryo, objetos não serializáveis)",
        ],
        "solucoes": [
            "Aumentar spark.driver/executor.memory",
            "Aumentar spark.shuffle.partitions, usar AQE",
            "Salting/repartition em chaves quentes",
            "Verificar YARN logs, aumentar overhead",
            "Registrar classes Kryo, evitar closures grandes",
        ],
        "runbooks": [
            "https://runbooks.interno/spark-oom",
            "https://runbooks.interno/spark-shuffle-spill",
            "https://runbooks.interno/spark-data-skew",
        ],
    },
    Dominio.KAFKA: {
        "causas_comuns": [
            "Consumer lag alto (processamento lento)",
            "Broker down (disco, rede, ZK)",
            "Under-replicated partitions",
            "ISR shrink/expand constante",
            "Producer timeout/retries esgotados",
        ],
        "solucoes": [
            "Escalar consumers, otimizar processamento",
            "Verificar broker logs, disco, rede, ZK",
            "Reassign partitions, verificar replica.lag",
            "Ajustar replica.fetch.max.bytes, min.isr",
            "Aumentar request.timeout.ms, retries",
        ],
        "runbooks": [
            "https://runbooks.interno/kafka-consumer-lag",
            "https://runbooks.interno/kafka-broker-down",
            "https://runbooks.interno/kafka-under-replicated",
        ],
    },
    Dominio.DATABASE: {
        "causas_comuns": [
            "Pool de conexões esgotado",
            "Slow query (missing index, stats desatualizadas)",
            "Deadlock / lock contention",
            "Replication lag (réplica atrasada)",
            "Disco cheio / tablespace cheio",
        ],
        "solucoes": [
            "Aumentar pool, fechar conexões vazando",
            "EXPLAIN ANALYZE, criar índice, ANALYZE/VACUUM",
            "Verificar transações longas, ordenar locks",
            "Verificar rede réplica, wal_sender status",
            "Limpar logs, expandir volume, partition",
        ],
        "runbooks": [
            "https://runbooks.interno/db-connection-pool",
            "https://runbooks.interno/db-slow-query",
            "https://runbooks.interno/db-deadlock",
        ],
    },
    Dominio.NETWORK: {
        "causas_comuns": [
            "DNS resolution failure",
            "Firewall/SG bloqueando tráfego",
            "TLS/SSL certificado expirado",
            "Load balancer health check falhando",
            "MTU mismatch / packet fragmentation",
        ],
        "solucoes": [
            "Verificar CoreDNS, /etc/resolv.conf",
            "Revisar security groups, network policies",
            "Renovar certificado (cert-manager, manual)",
            "Verificar backend health, readiness probe",
            "Ajustar MTU interface, path MTU discovery",
        ],
        "runbooks": [
            "https://runbooks.interno/network-dns",
            "https://runbooks.interno/network-firewall",
            "https://runbooks.interno/network-tls-cert",
        ],
    },
    Dominio.SECURITY: {
        "causas_comuns": [
            "Token expirado / inválido",
            "RBAC policy negando acesso",
            "Certificado mTLS inválido",
            "Vault selado / token expirado",
            "Política de compliance bloqueando",
        ],
        "solucoes": [
            "Renovar token, verificar audience/issuer",
            "Ajustar Role/ClusterRoleBinding",
            "Verificar CA, SAN, expiração cert",
            "Unseal Vault, renovar token app",
            "Revisar política, solicitar exceção",
        ],
        "runbooks": [
            "https://runbooks.interno/security-token-expired",
            "https://runbooks.interno/security-rbac-denied",
            "https://runbooks.interno/security-vault-sealed",
        ],
    },
}


class EspecialistaAgent:
    """Agente responsável por análise profunda de incidentes ambíguos."""

    def __init__(self, config: EspecialistaConfig):
        self.config = config
        self.usar_llm = config.usar_llm
        self.modelo_llm = config.modelo_llm
        self.base_conhecimento = BASE_CONHECIMENTO
        self._llm_client = None

        if self.usar_llm:
            self._init_llm()

        # Carrega base de conhecimento customizada se existir
        if config.base_conhecimento_path:
            self._carregar_base_conhecimento(config.base_conhecimento_path)

    def _init_llm(self) -> None:
        """Inicializa cliente LLM."""
        try:
            if "gpt" in self.modelo_llm.lower() or "openai" in self.modelo_llm.lower():
                from openai import OpenAI
                self._llm_client = OpenAI()
                logger.info(f"OpenAI client inicializado: {self.modelo_llm}")
            elif "claude" in self.modelo_llm.lower() or "anthropic" in self.modelo_llm.lower():
                from anthropic import Anthropic
                self._llm_client = Anthropic()
                logger.info(f"Anthropic client inicializado: {self.modelo_llm}")
            else:
                logger.warning(f"Modelo LLM não reconhecido: {self.modelo_llm}, usando mock")
                self.usar_llm = False
        except ImportError:
            logger.warning("SDK LLM não instalado, usando mock")
            self.usar_llm = False

    def _carregar_base_conhecimento(self, path: str) -> None:
        """Carrega base de conhecimento customizada (JSON)."""
        try:
            with open(path) as f:
                custom = json.load(f)
            # Merge com base padrão
            for dominio_str, dados in custom.items():
                try:
                    dominio = Dominio(dominio_str)
                    if dominio in self.base_conhecimento:
                        self.base_conhecimento[dominio].update(dados)
                    else:
                        self.base_conhecimento[dominio] = dados
                except ValueError:
                    pass
            logger.info(f"Base de conhecimento customizada carregada: {path}")
        except Exception as e:
            logger.warning(f"Erro ao carregar base customizada: {e}")

    def _analisar_mock(self, classificacao: ClassificacaoOutput, conteudo: str) -> AnaliseEspecialistaOutput:
        """Análise mock usando base de conhecimento local."""
        dominio = classificacao.dominio
        kb = self.base_conhecimento.get(dominio, {})

        # Seleciona causas/soluções baseadas em keywords no conteúdo
        conteudo_lower = conteudo.lower()
        causas_selecionadas = []
        solucoes_selecionadas = []

        for causa in kb.get("causas_comuns", []):
            # Heurística simples: se palavras da causa aparecem no conteúdo
            palavras_causa = causa.lower().split()
            if any(p in conteudo_lower for p in palavras_causa if len(p) > 3):
                causas_selecionadas.append(causa)

        for solucao in kb.get("solucoes", []):
            palavras_solucao = solucao.lower().split()
            if any(p in conteudo_lower for p in palavras_solucao if len(p) > 3):
                solucoes_selecionadas.append(solucao)

        # Fallback: usa as primeiras se nada matchou
        if not causas_selecionadas:
            causas_selecionadas = kb.get("causas_comuns", [])[:3]
        if not solucoes_selecionadas:
            solucoes_selecionadas = kb.get("solucoes", [])[:3]

        causa_raiz = "; ".join(causas_selecionadas[:2])
        solucao = "; ".join(solucoes_selecionadas[:2])

        return AnaliseEspecialistaOutput(
            causa_raiz=causa_raiz,
            solucao_sugerida=solucao,
            acoes_imediatas=solucoes_selecionadas[:3],
            acoes_preventivas=[
                f"Monitorar {dominio.value} proativamente",
                f"Configurar alertas para {dominio.value}",
                "Documentar incidente no runbook",
            ],
            referencias=kb.get("runbooks", [])[:3],
            classificacao_id=getattr(classificacao, "limpo_id", None),
        )

    def _analisar_llm(self, classificacao: ClassificacaoOutput, conteudo: str) -> AnaliseEspecialistaOutput:
        """Análise usando LLM."""
        if not self._llm_client:
            return self._analisar_mock(classificacao, conteudo)

        prompt = f"""
        Analise o incidente técnico abaixo e forneça:
        1. Causa raiz mais provável
        2. Solução imediata
        3. Ações preventivas
        4. Referências de runbooks/documentação

        Domínio: {classificacao.dominio.value}
        Severidade: {classificacao.severidade.value}
        Confiança da classificação: {classificacao.confianca:.2f}
        Tags: {', '.join(classificacao.tags)}

        Conteúdo do incidente (dados sensíveis já removidos):
        ---
        {conteudo[:4000]}
        ---

        Responda em JSON com campos:
        causa_raiz, solucao_sugerida, acoes_imediatas[], acoes_preventivas[], referencias[]
        """

        try:
            if hasattr(self._llm_client, "chat"):  # OpenAI
                response = self._llm_client.chat.completions.create(
                    model=self.modelo_llm,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                result = json.loads(response.choices[0].message.content)
            else:  # Anthropic
                response = self._llm_client.messages.create(
                    model=self.modelo_llm,
                    max_tokens=2000,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}]
                )
                result = json.loads(response.content[0].text)

            return AnaliseEspecialistaOutput(
                causa_raiz=result.get("causa_raiz", ""),
                solucao_sugerida=result.get("solucao_sugerida", ""),
                acoes_imediatas=result.get("acoes_imediatas", []),
                acoes_preventivas=result.get("acoes_preventivas", []),
                referencias=result.get("referencias", []),
                classificacao_id=getattr(classificacao, "limpo_id", None),
            )
        except Exception as e:
            logger.error(f"Erro no LLM: {e}, fallback para mock")
            return self._analisar_mock(classificacao, conteudo)

    def processar(self, arquivo_classificacao: str | Path) -> AnaliseEspecialistaOutput:
        """
        Processa classificação ambígua e gera análise profunda.

        Args:
            arquivo_classificacao: Caminho para .classificacao.json ou .record.json

        Returns:
            AnaliseEspecialistaOutput com causa raiz, solução, referências
        """
        entrada_path = Path(arquivo_classificacao)

        logger.info(f"Iniciando análise especialista: {entrada_path}")

        # Carrega classificação e conteúdo
        if entrada_path.suffix == ".json":
            # Tenta carregar como record primeiro
            try:
                record = carregar_json(entrada_path, PipelineRecord)
                if record.classificacao and record.classificacao.ambíguo:
                    classificacao = record.classificacao
                    conteudo = record.limpo.conteudo if record.limpo else record.bruto.conteudo
                    pipeline_id = record.pipeline_id
                else:
                    # Carrega como ClassificacaoOutput direto
                    classificacao = carregar_json(entrada_path, ClassificacaoOutput)
                    conteudo = ""  # Não tem conteúdo original
                    pipeline_id = classificacao.limpo_id
            except Exception:
                classificacao = carregar_json(entrada_path, ClassificacaoOutput)
                conteudo = ""
                pipeline_id = classificacao.limpo_id
        else:
            raise ValueError("Arquivo deve ser .json (classificação ou record)")

        if not classificacao.ambíguo:
            logger.info("Classificação não é ambígua, pulando análise especialista")
            return AnaliseEspecialistaOutput(
                causa_raiz="Classificação clara, não requer análise profunda",
                solucao_sugerida="Prosseguir para handoff direto",
                classificacao_id=pipeline_id,
            )

        # Executa análise
        if self.usar_llm:
            analise = self._analisar_llm(classificacao, conteudo)
        else:
            analise = self._analisar_mock(classificacao, conteudo)

        logger.info(f"Análise concluída: causa_raiz={analise.causa_raiz[:80]}...")

        # Salva análise
        saida_path = entrada_path.with_name(f"{entrada_path.stem}.analise.json")
        salvar_json(saida_path, analise)

        # Atualiza record se existir
        if entrada_path.name.endswith(".record.json"):
            record = atualizar_pipeline_record(
                record,
                StatusProcessamento.ANALYZED,
                analise=analise
            )
            salvar_json(entrada_path, record)

        return analise


def run_especialista(
    arquivo_classificacao: str,
    config: EspecialistaConfig | None = None
) -> AnaliseEspecialistaOutput:
    """Função de conveniência para executar o especialista."""
    if config is None:
        config = EspecialistaConfig(
            role=AgenteRole.ESPECIALISTA,
            input_path=arquivo_classificacao,
            output_path=arquivo_classificacao.replace(".json", ".analise.json")
        )

    agent = EspecialistaAgent(config)
    return agent.processar(arquivo_classificacao)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Agente Especialista - Análise profunda de incidentes ambíguos")
    parser.add_argument("entrada", help="Arquivo de classificação (.classificacao.json ou .record.json)")
    parser.add_argument("--config", help="Arquivo de configuração JSON")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--usar-llm", action="store_true", help="Usar LLM para análise")
    parser.add_argument("--modelo", default="gpt-4", help="Modelo LLM (gpt-4, claude-3, etc.)")

    args = parser.parse_args()

    global logger
    logger = setup_logging(args.log_level, "especialista")

    config = None
    if args.config:
        import json
        with open(args.config) as f:
            config_data = json.load(f)
        config = EspecialistaConfig(**config_data)
    else:
        config = EspecialistaConfig(
            role=AgenteRole.ESPECIALISTA,
            input_path=args.entrada,
            output_path=args.entrada.replace(".json", ".analise.json"),
            usar_llm=args.usar_llm,
            modelo_llm=args.modelo,
            log_level=args.log_level
        )

    try:
        resultado = run_especialista(args.entrada, config)
        print(f"✅ Análise concluída")
        print(f"   Causa raiz: {resultado.causa_raiz[:100]}...")
        print(f"   Solução: {resultado.solucao_sugerida[:100]}...")
        print(f"   Ações imediatas: {len(resultado.acoes_imediatas)}")
        print(f"   Referências: {len(resultado.referencias)}")
        return 0
    except Exception as e:
        logger.error(f"Falha na análise: {e}")
        print(f"❌ Erro: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())