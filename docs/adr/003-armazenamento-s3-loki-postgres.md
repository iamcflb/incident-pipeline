# ADR 003: Armazenamento - S3 (Objetos) + Loki (Logs) + PostgreSQL (Metadados)

## Status
Aceito

## Contexto
Precisamos armazenar:
1. Arquivos brutos e processados (logs, stacktraces) - volumes grandes, acesso infrequente
2. Logs estruturados para query/debug - alta cardinalidade, retention longo
3. Metadados de pipeline (status, timestamps, IDs) - relacional, queries complexas

## Decisão
| Tipo de Dado | Storage | Justificativa |
|--------------|---------|---------------|
| Arquivos brutos/limpos/classificações/análises/handoffs | **S3 (MinIO/CEPH/AWS S3)** | Barato, durável, versionamento, lifecycle policies |
| Logs estruturados (JSON) | **Loki** | Integrado com Grafana, labels para query, compression |
| Metadados de pipeline, RBAC, config | **PostgreSQL** | ACID, joins, migrations, ferramentas maduras |

## Esquema S3
```
s3://agent-incidents/
  ├── raw/
  │   └── {pipeline_id}/bruto.txt
  ├── redacted/
  │   └── {pipeline_id}/limpo.txt + .record.json
  ├── classified/
  │   └── {pipeline_id}/classificacao.json
  ├── analyzed/
  │   └── {pipeline_id}/analise.json
  └── handoff/
      └── {pipeline_id}/handoff.json + resultados.json
```

## Lifecycle Policy
- `raw/`: 30 dias → Glacier → 1 ano → Delete
- `redacted/`, `classified/`: 90 dias → IA → 2 anos → Delete
- `analyzed/`, `handoff/`: 1 ano → IA → 5 anos → Delete

## Justificativa
- **S3**: Decoupling compute/storage, custo baixo, compatível com qualquer cloud
- **Loki**: Purpose-built para logs, label-based query, multi-tenant
- **PostgreSQL**: Padrão da indústria para metadados relacionais

## Consequências
- 3 sistemas de storage para operar
- Necessita pipeline de sincronização (arquivo → S3 → DB metadata)
- Consistência eventual entre S3 e DB (aceitável)

## Alternativas Consideradas
1. **Tudo no PostgreSQL (BYTEA/JSONB)**: Simples, mas caro para blobs grandes, backup lento
2. **Tudo no S3 (Parquet/Delta Lake)**: Analytical, mas overkill para acesso pontual
3. **Elasticsearch para logs**: Poderoso, mas resource-heavy, licensing