"""
Testes para o Agente Redator.
"""
import tempfile
from pathlib import Path

import pytest
from agent_shared.schemas import AgenteRole, RedatorConfig

from redator.main import RedatorAgent, run_redator


class TestRedatorAgent:
    """Testes unitários do RedatorAgent."""

    @pytest.fixture
    def config(self):
        return RedatorConfig(
            role=AgenteRole.REDATOR,
            input_path="/tmp/bruto.txt",
            output_path="/tmp/limpo.txt",
            usar_trufflehog=False
        )

    @pytest.fixture
    def agent(self, config):
        return RedatorAgent(config)

    def test_redata_senha_simples(self, agent):
        """Testa redação de senha simples."""
        texto = "usuario=admin senha=minhasenha123 host=localhost"
        resultado, redacoes = agent.redatar_texto(texto)

        assert "minhasenha123" not in resultado
        assert "[REDACTED:SENHA]" in resultado
        assert "senha" in redacoes

    def test_redata_token(self, agent):
        """Testa redação de token."""
        texto = "Authorization: Bearer token=abc123xyz"
        resultado, redacoes = agent.redatar_texto(texto)

        assert "abc123xyz" not in resultado
        assert "[REDACTED:TOKEN]" in resultado
        assert "token" in redacoes

    def test_redata_jwt(self, agent):
        """Testa redação de JWT."""
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        texto = f"token={jwt}"
        resultado, redacoes = agent.redatar_texto(texto)

        assert jwt not in resultado
        assert "[REDACTED:JWT]" in resultado
        assert "jwt" in redacoes

    def test_redata_keytab(self, agent):
        """Testa redação de keytab."""
        texto = "keytab=/etc/krb5.keytab principal=user@REALM"
        resultado, redacoes = agent.redatar_texto(texto)

        assert "/etc/krb5.keytab" not in resultado
        assert "[REDACTED:KEYTAB]" in resultado
        assert "keytab" in redacoes

    def test_redata_aws_keys(self, agent):
        """Testa redação de chaves AWS."""
        texto = "AKIAIOSFODNN7EXAMPLE aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        resultado, redacoes = agent.redatar_texto(texto)

        assert "AKIAIOSFODNN7EXAMPLE" not in resultado
        assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in resultado
        assert any("AWS" in r.upper() for r in redacoes)

    def test_redata_db_url(self, agent):
        """Testa redação de URL de banco com credenciais."""
        texto = "DATABASE_URL=postgres://user:senha123@localhost:5432/db"
        resultado, redacoes = agent.redatar_texto(texto)

        assert "senha123" not in resultado
        assert "[REDACTED:DB_URL]" in resultado
        assert "db_url" in redacoes

    def test_redata_case_insensitive(self, agent):
        """Testa que redação é case-insensitive."""
        texto = "SENHA=secret123 Password=secret456 PaSsWoRd=secret789"
        resultado, redacoes = agent.redatar_texto(texto)

        assert "secret123" not in resultado
        assert "secret456" not in resultado
        assert "secret789" not in resultado
        assert redacoes.count("senha") == 3

    def test_nao_redata_texto_limpo(self, agent):
        """Testa que texto sem secrets não é alterado."""
        texto = "Erro: Connection timeout after 30s host=prod-db-01"
        resultado, redacoes = agent.redatar_texto(texto)

        assert resultado == texto
        assert redacoes == []

    def test_processar_arquivo_completo(self, agent):
        """Testa processamento completo de arquivo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "bruto.txt"
            saida = Path(tmpdir) / "limpo.txt"

            conteudo = """
            Iniciando job Airflow...
            senha=supersecreto
            token=abc123
            Conectando em postgres://admin:pass@db:5432/airflow
            Job finalizado com erro.
            """
            entrada.write_text(conteudo)

            resultado = agent.processar(entrada, saida)

            assert saida.exists()
            conteudo_limpo = saida.read_text()
            assert "supersecreto" not in conteudo_limpo
            assert "abc123" not in conteudo_limpo
            assert "pass" not in conteudo_limpo
            assert "[REDACTED:" in conteudo_limpo
            assert len(resultado.redacoes_aplicadas) >= 3

            # Verifica record
            record_path = saida.with_suffix(".record.json")
            assert record_path.exists()

    def test_padroes_customizados(self):
        """Testa patterns customizados."""
        config = RedatorConfig(
            role=AgenteRole.REDATOR,
            input_path="/tmp/bruto.txt",
            output_path="/tmp/limpo.txt",
            padroes_customizados=[r"minha_chave_secreta=[^\s]+"]
        )
        agent = RedatorAgent(config)

        texto = "minha_chave_secreta=valor123 outra_coisa=abc"
        resultado, redacoes = agent.redatar_texto(texto)

        assert "valor123" not in resultado
        assert "[REDACTED:CUSTOM]" in resultado
        assert "custom" in redacoes


class TestRunRedator:
    """Testes de integração da função run_redator."""

    def test_run_redator_cli_style(self):
        """Testa execução estilo CLI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entrada = Path(tmpdir) / "bruto.txt"
            saida = Path(tmpdir) / "limpo.txt"

            entrada.write_text("senha=123 token=abc")

            resultado = run_redator(str(entrada), str(saida))

            assert saida.exists()
            assert "123" not in saida.read_text()
            assert "abc" not in saida.read_text()
            assert len(resultado.redacoes_aplicadas) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])