# ADR 002: Comunicação via Arquivos + S3 (Eventual Kafka)

## Status
Aceito

## Contexto
Agentes independentes precisam trocar dados: bruto.txt → limpo.txt → classificação → análise → handoff.

## Decisão
**Fase 1 (Dev/Staging)**: Comunicação via sistema de arquivos compartilhado (PVC NFS) + JSON para metadados.
**Fase 2 (Produção)**: Migração para S3 (objetos) + Kafka (eventos de coordenação).

## Formato de Troca
- **Dados principais**: Arquivos `.txt` (conteúdo) + `.json` (metadados/record)
- **Pipeline Record**: JSON único que acompanha o fluxo (`pipeline_id` correlação)
- **Schema**: Pydantic models em `shared/schemas.py`

## Justificativa
- **Simplicidade inicial**: Arquivos funcionam localmente e em k8s com PVC compartilhado
- **Durabilidade**: Arquivos persistem falhas de pod
- **Debugging**: Fácil inspecionar `/data/in` e `/data/out`
- **Evolução**: S3/Kafka são drop-in replacements (mesmo contrato)

## Consequências
- Latência maior que gRPC/REST direto (aceitável para batch)
- Necessita lock/coordenação para evitar processamento duplicado
- PVC ReadWriteMany pode ser gargalo (mitigado com S3 na Fase 2)

## Alternativas Consideradas
1. **gRPC entre agentes**: Baixa latência, mas acoplamento temporal, retry complexo
2. **REST API**: Padronizado, mas requer service discovery, health checks
3. **Kafka only**: Ótimo para eventos, mas overkill para payloads grandes (logs)
4. **Database compartilhada**: ACID, mas schema coupling, connection pooling