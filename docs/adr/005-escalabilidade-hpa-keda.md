# ADR 005: Escalabilidade - K8s HPA + KEDA para Event-Driven Scaling

## Status
Aceito

## Contexto
Picos de incidentes (ex: Airflow com 100 erros simultâneos) exigem escala rápida.
Agentes têm perfis de carga diferentes:
- **Redator**: CPU-bound (regex), escala horizontal fácil
- **Triador**: CPU-bound (keyword/ML), escala horizontal
- **Especialista**: LLM-bound (latência alta, custo alto), escala limitada
- **Handoff**: I/O-bound (APIs externas), escala horizontal com rate limiting

## Decisão

### Horizontal Pod Autoscaler (HPA) para todos
```yaml
# Exemplo para Triador
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-triador-hpa
  namespace: agent-system
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agent-triador
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: queue_depth
        target:
          type: AverageValue
          averageValue: "10"  # 10 arquivos por pod
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
```

### KEDA para Event-Driven Scaling (Fase 2)
Quando migrar para Kafka/S3 events:
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: agent-triador-keda
  namespace: agent-system
spec:
  scaleTargetRef:
    name: agent-triador
  pollingInterval: 15
  cooldownPeriod: 300
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka:9092
        consumerGroup: triador-scaler
        topic: incidents-to-classify
        lagThreshold: "10"
    - type: cpu
      metadata:
        type: Utilization
        value: "70"
```

### Resource Quotas por Agente
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: agent-redator-quota
  namespace: agent-system
spec:
  hard:
    requests.cpu: "2"
    requests.memory: 2Gi
    limits.cpu: "4"
    limits.memory: 4Gi
    pods: "10"
```

### Prioridade e Preemption
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: agent-critical
value: 1000000
globalDefault: false
description: "Agentes de handoff e triagem crítica"
---
# No deployment do Handoff:
priorityClassName: agent-critical
```

## Justificativa
- **HPA nativo**: Simples, baseado em CPU/métricas customizadas
- **KEDA**: Escala baseada em fila (Kafka, S3 events, Prometheus), zero-to-N
- **ResourceQuotas**: Evita noisy neighbor, garante fair sharing
- **PriorityClass**: Handoff nunca fica pending por falta de recursos

## Consequências
- HPA reage a CPU (lag de ~1-2 min)
- KEDA reage a eventos (segundos), mas adiciona dependência
- Especialista com LLM pode ter maxReplicas baixo (custo)
- Rate limiting externo (Jira/Slack API) pode exigir backoff

## Alternativas Consideradas
1. **Cluster Autoscaler only**: Escala nodes, não pods; lento para picos
2. **CronHPA**: Previsível, mas não reage a picos inesperados
3. **Knative Serving**: Scale-to-zero, mas complexidade extra
4. **Custom controller**: Controle total, mas reinventar roda