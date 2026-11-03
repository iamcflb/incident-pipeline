"""
Agente Triador - Implementação principal.

Classifica domínio usando:
1. Keyword matching (rápido, sem dependências)
2. ML opcional (scikit-learn) para maior precisão
"""
import argparse
import sys
from pathlib import Path

from agent_shared.schemas import (
    AgenteRole,
    ClassificacaoOutput,
    Dominio,
    PipelineRecord,
    Severidade,
    StatusProcessamento,
    TriadorConfig,
)
from agent_shared.utils import (
    atualizar_pipeline_record,
    carregar_json,
    gerar_pipeline_id,
    salvar_json,
    setup_logging,
)

logger = setup_logging("INFO", "triador")


# ===================== Keyword Patterns =====================

PALAVRAS_CHAVE_DOMINIO = {
    Dominio.AIRFLOW: [
        "airflow", "dag", "taskinstance", "scheduler", "webserver",
        "celeryexecutor", "localexecutor", "kubernetesexecutor",
        "xcom", "sensor", "operator", "hook", "pool", "queue",
        "airflow.cfg", "airflow.db", "metadata database",
    ],
    Dominio.KUBERNETES: [
        "kubernetes", "k8s", "kubectl", "pod", "deployment", "service",
        "ingress", "configmap", "secret", "namespace", "node",
        "kubelet", "kube-proxy", "apiserver", "etcd", "controller-manager",
        "scheduler", "cni", "csi", "rbac", "crb", "rolebinding",
        "helm", "chart", "release", "values.yaml", "kustomize",
        "crashloopbackoff", "oomkilled", "imagepullbackoff", "pending",
        "evicted", "containercreating", "runc", "containerd", "cri-o",
    ],
    Dominio.HADOOP: [
        "hadoop", "hdfs", "namenode", "datanode", "yarn", "resourcemanager",
        "nodemanager", "mapreduce", "hive", "hbase", "zookeeper",
        "hdfs dfs", "fsck", "block", "replication", "rack awareness",
    ],
    Dominio.SPARK: [
        "spark", "pyspark", "spark-submit", "spark-sql", "dataframe",
        "rdd", "driver", "executor", "shuffle", "partition",
        "broadcast", "accumulator", "checkpoint", "lineage",
        "spark.ui", "spark.history", "eventlog",
    ],
    Dominio.KAFKA: [
        "kafka", "zookeeper", "broker", "topic", "partition", "replica",
        "producer", "consumer", "consumer group", "offset", "lag",
        "kafka-connect", "kafka-streams", "ksql", "schema registry",
        "isr", "leader", "controller", "log.dirs",
    ],
    Dominio.DATABASE: [
        "postgresql", "postgres", "mysql", "mongodb", "redis", "cassandra",
        "elasticsearch", "sql", "query", "transaction", "deadlock",
        "connection pool", "slow query", "index", "vacuum", "analyze",
        "replication", "failover", "backup", "restore",
    ],
    Dominio.NETWORK: [
        "timeout", "connection refused", "connection reset", "dns",
        "tcp", "udp", "http", "https", "proxy", "load balancer",
        "firewall", "iptables", "network policy", "service mesh",
        "istio", "linkerd", "envoy", "tls", "ssl", "certificate",
    ],
    Dominio.SECURITY: [
        "unauthorized", "forbidden", "authentication", "authorization",
        "rbac", "certificate", "tls", "ssl", "vault", "secret",
        "encryption", "decryption", "audit", "compliance", "cis",
        "penetration", "vulnerability", "cve", "patch",
    ],
}

# Palavras que indicam severidade
PALAVRAS_SEVERIDADE = {
    Severidade.CRITICAL: [
        "critical", "fatal", "panic", "crash", "outage", "down",
        "data loss", "corruption", "unreachable", "unavailable",
    ],
    Severidade.HIGH: [
        "error", "fail", "failed", "exception", "timeout",
        "denied", "refused", "reject", "abort",
    ],
    Severidade.MEDIUM: [
        "warn", "warning", "retry", "degraded", "slow", "latency",
        "backlog", "queue", "pending",
    ],
    Severidade.LOW: [
        "info", "debug", "trace", "notice", "starting", "started",
        "completed", "success",
    ],
}


class TriadorAgent:
    """Agente responsável por classificar domínio de incidentes."""

    def __init__(self, config: TriadorConfig):
        self.config = config
        self.modelo = config.modelo_classificacao
        self.threshold = config.threshold_confianca
        self._ml_model = None
        self._ml_vectorizer = None

        if self.modelo == "ml":
            self._init_ml()

    def _init_ml(self) -> None:
        """Inicializa modelo ML se disponível."""
        try:
            import joblib
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression

            # Tenta carregar modelo treinado
            model_path = Path(self.config.input_path).parent / "models" / "triador_model.joblib"
            vec_path = Path(self.config.input_path).parent / "models" / "triador_vectorizer.joblib"

            if model_path.exists() and vec_path.exists():
                self._ml_model = joblib.load(model_path)
                self._ml_vectorizer = joblib.load(vec_path)
                logger.info("Modelo ML carregado")
            else:
                logger.warning("Modelo ML não encontrado, usando keyword matching")
                self.modelo = "keyword"
        except ImportError:
            logger.warning("scikit-learn não instalado, usando keyword matching")
            self.modelo = "keyword"

    def _classificar_keyword(self, texto: str) -> tuple[Dominio, float, list[str]]:
        """Classifica usando keyword matching."""
        texto_lower = texto.lower()
        scores = {}
        tags_encontradas = []

        for dominio, palavras in PALAVRAS_CHAVE_DOMINIO.items():
            score = 0
            for palavra in palavras:
                if palavra.lower() in texto_lower:
                    score += 1
                    tags_encontradas.append(palavra)
            scores[dominio] = score

        if not scores or max(scores.values()) == 0:
            return Dominio.UNKNOWN, 0.0, []

        melhor_dominio = max(scores, key=scores.get)
        max_score = scores[melhor_dominio]

        # Normaliza confiança (heurística simples)
        total_palavras = len(PALAVRAS_CHAVE_DOMINIO[melhor_dominio])
        confianca = min(max_score / max(total_palavras * 0.3, 1), 1.0)

        return melhor_dominio, confianca, tags_encontradas

    def _classificar_ml(self, texto: str) -> tuple[Dominio, float, list[str]]:
        """Classifica usando modelo ML."""
        if not self._ml_model or not self._ml_vectorizer:
            return self._classificar_keyword(texto)

        try:
            X = self._ml_vectorizer.transform([texto])
            probas = self._ml_model.predict_proba(X)[0]
            classes = self._ml_model.classes_

            idx_max = probas.argmax()
            confianca = float(probas[idx_max])
            dominio_str = classes[idx_max]

            try:
                dominio = Dominio(dominio_str)
            except ValueError:
                dominio = Dominio.UNKNOWN

            return dominio, confianca, []
        except Exception as e:
            logger.warning(f"Erro no modelo ML: {e}, fallback para keyword")
            return self._classificar_keyword(texto)

    def _determinar_severidade(self, texto: str) -> Severidade:
        """Determina severidade baseada em palavras-chave."""
        texto_lower = texto.lower()

        for severidade, palavras in PALAVRAS_SEVERIDADE.items():
            for palavra in palavras:
                if palavra.lower() in texto_lower:
                    return severidade

        return Severidade.MEDIUM

    def processar(self, arquivo_limpo: str | Path) -> ClassificacaoOutput:
        """
        Processa arquivo limpo e gera classificação.

        Args:
            arquivo_limpo: Caminho para limpo.txt ou limpo.record.json

        Returns:
            ClassificacaoOutput com domínio, severidade, confiança
        """
        entrada_path = Path(arquivo_limpo)

        logger.info(f"Iniciando triagem: {entrada_path}")

        # Carrega conteúdo (pode ser .txt ou .record.json)
        if entrada_path.suffix == ".json":
            record = carregar_json(entrada_path, PipelineRecord)
            conteudo = record.limpo.conteudo if record.limpo else record.bruto.conteudo
            pipeline_id = record.pipeline_id
        else:
            conteudo = entrada_path.read_text(encoding="utf-8")
            pipeline_id = gerar_pipeline_id(conteudo)

        # Classifica domínio
        if self.modelo == "ml":
            dominio, confianca, tags = self._classificar_ml(conteudo)
        else:
            dominio, confianca, tags = self._classificar_keyword(conteudo)

        # Determina severidade
        severidade = self._determinar_severidade(conteudo)

        # Verifica se é ambíguo
        ambíguo = confianca < self.threshold

        # Cria output
        classificacao = ClassificacaoOutput(
            dominio=dominio,
            confianca=confianca,
            severidade=severidade,
            tags=tags,
            ambíguo=ambíguo,
            limpo_id=pipeline_id,
        )

        logger.info(f"Classificação: {dominio.value} (confiança: {confianca:.2f}, severidade: {severidade.value}, ambíguo: {ambíguo})")

        # Salva classificação
        saida_path = entrada_path.with_name(f"{entrada_path.stem}.classificacao.json")
        salvar_json(saida_path, classificacao)

        # Atualiza record se existir
        if entrada_path.suffix == ".json":
            record = atualizar_pipeline_record(
                record,
                StatusProcessamento.CLASSIFIED,
                classificacao=classificacao
            )
            salvar_json(entrada_path, record)

        return classificacao


def run_triador(
    arquivo_limpo: str,
    config: TriadorConfig | None = None
) -> ClassificacaoOutput:
    """Função de conveniência para executar o triador."""
    if config is None:
        config = TriadorConfig(
            role=AgenteRole.TRIADOR,
            input_path=arquivo_limpo,
            output_path=arquivo_limpo.replace(".txt", ".classificacao.json")
        )

    agent = TriadorAgent(config)
    return agent.processar(arquivo_limpo)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Agente Triador - Classifica domínio de incidentes")
    parser.add_argument("entrada", help="Arquivo limpo (limpo.txt ou .record.json)")
    parser.add_argument("--config", help="Arquivo de configuração JSON")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--modelo", choices=["keyword", "ml"], default="keyword", help="Modelo de classificação")
    parser.add_argument("--threshold", type=float, default=0.7, help="Threshold de confiança para ambíguo")

    args = parser.parse_args()

    global logger
    logger = setup_logging(args.log_level, "triador")

    config = None
    if args.config:
        import json
        with open(args.config) as f:
            config_data = json.load(f)
        config = TriadorConfig(**config_data)
    else:
        config = TriadorConfig(
            role=AgenteRole.TRIADOR,
            input_path=args.entrada,
            output_path=args.entrada.replace(".txt", ".classificacao.json"),
            modelo_classificacao=args.modelo,
            threshold_confianca=args.threshold,
            log_level=args.log_level
        )

    try:
        resultado = run_triador(args.entrada, config)
        print(f"✅ Classificação: {resultado.dominio.value}")
        print(f"   Confiança: {resultado.confianca:.2f}")
        print(f"   Severidade: {resultado.severidade.value}")
        print(f"   Ambíguo: {resultado.ambíguo}")
        print(f"   Tags: {', '.join(resultado.tags) if resultado.tags else 'nenhuma'}")
        return 0
    except Exception as e:
        logger.error(f"Falha na triagem: {e}")
        print(f"❌ Erro: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())