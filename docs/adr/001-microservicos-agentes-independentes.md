# ADR 001: Micro-agentes como Serviços Independentes

## Status
Aceito

## Contexto
Precisamos processar incidentes técnicos através de um pipeline: Redação → Triagem → Especialista → Handoff.
Cada etapa tem requisitos diferentes de recursos, latência, e escala.

## Decisão
Cada agente será um **microserviço independente** deployado separadamente no Kubernetes.

## Justificativa
- **Escala independente**: Redator (CPU-leve) escala diferente de Especialista (LLM, GPU opcional)
- **Falha isolada**: Bug no Handoff não derruba Redator
- **Deploy independente**: Atualizar Triador não requer rebuild do Especialista
- **Times autônomos**: Cada time pode evoluir seu agente
- **Tecnologia heterogênea**: Redator em Go (performance), Especialista em Python (ML/LLM)

## Consequências
- Complexidade operacional maior (4 deployments, 4 services)
- Comunicação via arquivos/S3/filas em vez de chamadas de função
- Necessita contratos de dados bem definidos (schemas compartilhados)
- Observabilidade distribuída (traces, logs correlacionados)

## Alternativas Consideradas
1. **Monolito único**: Simples, mas escala tudo junto, deploy acoplado
2. **Funções no mesmo processo**: Baixa latência, mas falha derruba tudo, não escala independentemente
3. **Workflow engine (Airflow/Temporal)**: Bom para orquestração, mas adiciona dependência externa pesada