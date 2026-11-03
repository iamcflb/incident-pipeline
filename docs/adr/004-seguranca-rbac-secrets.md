# ADR 004: Segurança - RBAC por Agente + Secrets via Vault/SealedSecrets

## Status
Aceito

## Contexto
Agentes processam dados sensíveis (logs com credenciais) e acessam sistemas externos (Jira, Slack, DB).
Precisamos controlar: quem pode acessar o quê, e como gerenciar secrets.

## Decisão

### RBAC Kubernetes por Agente
Cada agente tem seu próprio `ServiceAccount` + `Role` + `RoleBinding` no namespace `agent-system`.

| Agente | ServiceAccount | Permissões |
|--------|----------------|------------|
| Redator | `agent-redator` | Read config, Read/Write PVC data |
| Triador | `agent-triador` | Read config, Read/Write PVC data |
| Especialista | `agent-especialista` | Read config, Read/Write PVC data, Read secrets (LLM keys) |
| Handoff | `agent-handoff` | Read config, Read/Write PVC data, Read secrets (Jira, Slack, SMTP) |

### Secrets Management
- **Desenvolvimento**: Kubernetes Secrets (base64, não criptografado em etcd)
- **Produção**: **SealedSecrets** (Bitnami) ou **HashiCorp Vault** com CSI driver
- **Rotation**: Automatizado via Vault/SealedSecrets controller

### Network Policies
```yaml
# Exemplo: Redator só fala com Triador via arquivo compartilhado, não rede
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: agent-redator-egress
spec:
  podSelector:
    matchLabels:
      app: agent-redator
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: agent-triador
      ports:
        - protocol: TCP
          port: 8080  # Se houver API futura
```

### Pod Security Standards
- `runAsNonRoot: true`
- `runAsUser: 1000`
- `readOnlyRootFilesystem: true` (exceto /data, /tmp)
- `capabilities: drop: [ALL]`

## Justificativa
- **Princípio do menor privilégio**: Cada agente só acessa o que precisa
- **Auditoria**: Logs de acesso por ServiceAccount
- **Compliance**: Secrets nunca em código/imagem, rotação automática

## Consequências
- Mais objetos Kubernetes para gerenciar
- Vault/SealedSecrets adicionam dependência operacional
- Network policies podem dificultar debugging (mitigado com logs)

## Alternativas Consideradas
1. **ServiceAccount único para todos**: Simples, mas viola menor privilégio
2. **Istio mTLS + AuthZ**: Poderoso, mas complexidade operacional alta
3. **Secrets em ConfigMap**: Inseguro, não recomendado