"""
Agente Redator - Implementação principal.

Remove dados sensíveis usando regex patterns + opcionalmente truffleHog3.
"""
import argparse
import sys
from pathlib import Path

from agent_shared.schemas import (
    AgenteRole,
    BrutoInput,
    LimpoOutput,
    PipelineRecord,
    RedatorConfig,
    StatusProcessamento,
)
from agent_shared.utils import (
    atualizar_pipeline_record,
    compilar_padroes,
    gerar_pipeline_id,
    redatar_texto,
    salvar_json,
    setup_logging,
)

logger = setup_logging("INFO", "redator")


class RedatorAgent:
    """Agente responsável por remover dados sensíveis."""

    def __init__(self, config: RedatorConfig):
        self.config = config
        self.padroes = compilar_padroes(config.padroes_customizados)
        self.usar_trufflehog = config.usar_trufflehog
        self._trufflehog_scanner = None

        if self.usar_trufflehog:
            self._init_trufflehog()

    def _init_trufflehog(self) -> None:
        """Inicializa truffleHog3 scanner se disponível."""
        try:
            from trufflehog3 import trufflehog3
            self._trufflehog_scanner = trufflehog3.TruffleHog3()
            logger.info("truffleHog3 inicializado")
        except ImportError:
            logger.warning("truffleHog3 não instalado, usando apenas regex")
            self.usar_trufflehog = False

    def redatar_texto(self, texto: str) -> tuple[str, list[str]]:
        """Método público para redação de texto (usado em testes)."""
        return redatar_texto(texto, self.padroes)

    def processar(self, arquivo_entrada: str | Path, arquivo_saida: str | Path) -> LimpoOutput:
        """
        Processa arquivo bruto e gera arquivo limpo.

        Args:
            arquivo_entrada: Caminho para bruto.txt
            arquivo_saida: Caminho para limpo.txt

        Returns:
            LimpoOutput com metadados da redação
        """
        entrada_path = Path(arquivo_entrada)
        saida_path = Path(arquivo_saida)

        logger.info(f"Iniciando redação: {entrada_path} -> {saida_path}")

        # Lê arquivo bruto
        try:
            conteudo_bruto = entrada_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Erro ao ler {entrada_path}: {e}")
            raise

        # Cria record do pipeline
        pipeline_id = gerar_pipeline_id(conteudo_bruto)
        bruto_input = BrutoInput(
            conteudo=conteudo_bruto,
            fonte=str(entrada_path),
            metadata={"pipeline_id": pipeline_id}
        )

        record = PipelineRecord(
            pipeline_id=pipeline_id,
            bruto=bruto_input,
            status=StatusProcessamento.PENDING
        )

        # Aplica redação via regex
        conteudo_limpo, redacoes_regex = redatar_texto(conteudo_bruto, self.padroes)

        # Aplica truffleHog3 se habilitado
        redacoes_trufflehog = []
        if self.usar_trufflehog and self._trufflehog_scanner:
            try:
                # truffleHog3 encontra secrets no conteúdo
                findings = self._trufflehog_scanner.scan_string(conteudo_bruto)
                for finding in findings:
                    # Redata o segredo encontrado
                    segredo = finding.get("Raw", "")
                    if segredo and segredo in conteudo_limpo:
                        conteudo_limpo = conteudo_limpo.replace(segredo, f"[REDACTED:TRUFFLEHOG_{finding.get('DetectorType','SECRET')}]")
                        redacoes_trufflehog.append(f"trufflehog_{finding.get('DetectorType','secret').lower()}")
            except Exception as e:
                logger.warning(f"Erro no truffleHog3: {e}")

        # Combina redacoes
        todas_redacoes = redacoes_regex + redacoes_trufflehog

        # Grava arquivo limpo
        try:
            saida_path.write_text(conteudo_limpo, encoding="utf-8")
        except Exception as e:
            logger.error(f"Erro ao gravar {saida_path}: {e}")
            raise

        # Cria output
        limpo_output = LimpoOutput(
            conteudo=conteudo_limpo,
            redacoes_aplicadas=todas_redacoes,
        )

        # Atualiza record
        record = atualizar_pipeline_record(
            record,
            StatusProcessamento.REDACTED,
            limpo=limpo_output
        )

        # Salva record para auditoria/handoff
        record_path = saida_path.with_suffix(".record.json")
        salvar_json(record_path, record)

        logger.info(f"Redação concluída: {len(todas_redacoes)} ocorrências redatadas")
        logger.info(f"Record salvo em: {record_path}")

        return limpo_output


def run_redator(
    arquivo_entrada: str,
    arquivo_saida: str,
    config: RedatorConfig | None = None
) -> LimpoOutput:
    """Função de conveniência para executar o redator."""
    if config is None:
        config = RedatorConfig(
            role=AgenteRole.REDATOR,
            input_path=arquivo_entrada,
            output_path=arquivo_saida
        )

    agent = RedatorAgent(config)
    return agent.processar(arquivo_entrada, arquivo_saida)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Agente Redator - Remove dados sensíveis")
    parser.add_argument("entrada", help="Arquivo de entrada (bruto.txt)")
    parser.add_argument("saida", help="Arquivo de saída (limpo.txt)")
    parser.add_argument("--config", help="Arquivo de configuração JSON")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--trufflehog", action="store_true", help="Usar truffleHog3 para detectar secrets")

    args = parser.parse_args()

    # Reconfigura logging
    global logger
    logger = setup_logging(args.log_level, "redator")

    # Carrega config se fornecido
    config = None
    if args.config:
        import json
        with open(args.config) as f:
            config_data = json.load(f)
        config = RedatorConfig(**config_data)
    else:
        config = RedatorConfig(
            role=AgenteRole.REDATOR,
            input_path=args.entrada,
            output_path=args.saida,
            usar_trufflehog=args.trufflehog,
            log_level=args.log_level
        )

    try:
        resultado = run_redator(args.entrada, args.saida, config)
        print(f"✅ Redação concluída: {len(resultado.redacoes_aplicadas)} ocorrências")
        for r in resultado.redacoes_aplicadas:
            print(f"  - {r}")
        return 0
    except Exception as e:
        logger.error(f"Falha na redação: {e}")
        print(f"❌ Erro: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())