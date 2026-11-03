"""
Testes para shared/utils.py
"""
import pytest
from datetime import datetime

from agent_shared.utils import (
    setup_logging,
    gerar_pipeline_id,
    salvar_json,
    carregar_json,
    compilar_padroes,
    redatar_texto,
    PADROES_SENSIVEIS_DEFAULT,
)
from agent_shared.schemas import PipelineRecord, StatusProcessamento, BrutoInput, LimpoOutput


class TestUtils:
    """Testes das utilitárias compartilhadas."""

    def test_setup_logging(self):
        """Testa configuração de logging."""
        logger = setup_logging("DEBUG", "test-agent")
        assert logger.level == 10  # DEBUG
        assert logger.name == "test-agent"

    def test_gerar_pipeline_id(self):
        """Testa geração de ID único."""
        conteudo = "test content"
        id1 = gerar_pipeline_id(conteudo)
        id2 = gerar_pipeline_id(conteudo)

        assert id1.startswith("pipe-")
        # IDs devem ser diferentes (counter garante unicidade)
        assert id1 != id2
        # Mas hash do conteúdo deve ser mesmo (penúltimo elemento)
        assert id1.split("-")[-2] == id2.split("-")[-2]

    def test_gerar_pipeline_id_diferente_conteudo(self):
        """Testa que conteúdo diferente gera hash diferente."""
        id1 = gerar_pipeline_id("conteudo 1")
        id2 = gerar_pipeline_id("conteudo 2")
        assert id1.split("-")[-2] != id2.split("-")[-2]

    def test_salvar_carregar_json(self, tmp_path):
        """Testa salvamento e carregamento de JSON."""
        arquivo = tmp_path / "test.json"
        dados = {"chave": "valor", "numero": 42, "lista": [1, 2, 3]}

        salvar_json(arquivo, dados)
        carregados = carregar_json(arquivo)

        assert carregados == dados

    def test_salvar_carregar_pydantic(self, tmp_path):
        """Testa salvamento e carregamento de modelo Pydantic."""
        arquivo = tmp_path / "record.json"

        bruto = BrutoInput(conteudo="teste", fonte="arquivo.txt")
        record = PipelineRecord(pipeline_id="pipe-123", bruto=bruto)

        salvar_json(arquivo, record)
        carregado = carregar_json(arquivo, PipelineRecord)

        assert isinstance(carregado, PipelineRecord)
        assert carregado.pipeline_id == "pipe-123"
        assert carregado.bruto.conteudo == "teste"

    def test_compilar_padroes_default(self):
        """Testa compilação dos padrões default."""
        padroes = compilar_padroes()
        assert len(padroes) == len(PADROES_SENSIVEIS_DEFAULT)
        for pattern, label in padroes:
            assert hasattr(pattern, "search")
            assert isinstance(label, str)

    def test_compilar_padroes_customizados(self):
        """Testa compilação com padrões customizados."""
        custom = [r"minha_chave=[^\s]+"]
        padroes = compilar_padroes(custom)
        assert len(padroes) == len(PADROES_SENSIVEIS_DEFAULT) + 1
        # Último deve ser o custom
        assert padroes[-1][1] == "custom"

    def test_redatar_texto_senha(self):
        """Testa redação de senha."""
        texto = "usuario=admin senha=minhasenha123 host=localhost"
        resultado, redacoes = redatar_texto(texto)

        assert "minhasenha123" not in resultado
        assert "[REDACTED:SENHA]" in resultado
        assert "senha" in redacoes

    def test_redatar_texto_token(self):
        """Testa redação de token."""
        texto = "Authorization: Bearer token=abc123xyz"
        resultado, redacoes = redatar_texto(texto)

        assert "abc123xyz" not in resultado
        assert "[REDACTED:TOKEN]" in resultado
        assert "token" in redacoes

    def test_redatar_texto_jwt(self):
        """Testa redação de JWT."""
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        texto = f"token={jwt}"
        resultado, redacoes = redatar_texto(texto)

        assert jwt not in resultado
        assert "[REDACTED:JWT]" in resultado
        assert "jwt" in redacoes

    def test_redatar_texto_keytab(self):
        """Testa redação de keytab."""
        texto = "keytab=/etc/krb5.keytab principal=user@REALM"
        resultado, redacoes = redatar_texto(texto)

        assert "/etc/krb5.keytab" not in resultado
        assert "[REDACTED:KEYTAB]" in resultado
        assert "keytab" in redacoes

    def test_redatar_texto_aws_keys(self):
        """Testa redação de chaves AWS."""
        texto = "AKIAIOSFODNN7EXAMPLE aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        resultado, redacoes = redatar_texto(texto)

        assert "AKIAIOSFODNN7EXAMPLE" not in resultado
        assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in resultado
        assert any("AWS" in r.upper() for r in redacoes)

    def test_redatar_texto_db_url(self):
        """Testa redação de URL de banco."""
        texto = "DATABASE_URL=postgres://user:senha123@localhost:5432/db"
        resultado, redacoes = redatar_texto(texto)

        assert "senha123" not in resultado
        assert "[REDACTED:DB_URL]" in resultado
        assert "db_url" in redacoes

    def test_redatar_case_insensitive(self):
        """Testa que redação é case-insensitive."""
        texto = "SENHA=secret123 Password=secret456 PaSsWoRd=secret789"
        resultado, redacoes = redatar_texto(texto)

        assert "secret123" not in resultado
        assert "secret456" not in resultado
        assert "secret789" not in resultado
        assert redacoes.count("senha") == 3

    def test_redatar_texto_limpo(self):
        """Testa que texto sem secrets não é alterado."""
        texto = "Erro: Connection timeout after 30s host=prod-db-01"
        resultado, redacoes = redatar_texto(texto)

        assert resultado == texto
        assert redacoes == []

    def test_redatar_multiplas_ocorrencias(self):
        """Testa múltiplas ocorrências do mesmo padrão."""
        texto = "senha=123 senha=456 token=abc token=def"
        resultado, redacoes = redatar_texto(texto)

        assert resultado.count("[REDACTED:SENHA]") == 2
        assert resultado.count("[REDACTED:TOKEN]") == 2
        assert redacoes.count("senha") == 2
        assert redacoes.count("token") == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])