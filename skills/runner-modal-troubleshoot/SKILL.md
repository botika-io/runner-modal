---
name: runner-modal-troubleshoot
description: >-
  Diagnoses runner-modal failures (webhook 401/204/503, admit misses,
  jobs queued forever). Use when a self-hosted Modal Actions job never
  starts or the webhook ignores a delivery. Not for generic Actions
  debugging.
---

# Troubleshooting runner-modal

| Symptom | Check |
|---------|--------|
| HTTP 401 | Webhook secret ≠ Modal `WEBHOOK_SECRET` |
| HTTP 204 + `X-Runner-Modal-Reason` | Admit miss (below) |
| HTTP 503 | Soft `max_concurrent`, or delivery in flight |
| Queued forever | Sandbox logs; `GET /health`; Function URL, not a Server |
| Matrix collision | Two legs share the same pin |
| Webhook never hits Modal | Events ≠ **Workflow jobs**; URL missing `/github` |

Admit reasons: `repository_mismatch`, `missing_self_hosted`,
`label_mismatch`. `None` means admitted.

```bash
curl -sS "$URL/health"
```

Webhook Function logs: `modal app logs <app-name>`. JIT / boot: Sandbox
logs. Do not switch the webhook to a Modal Server to “fix” 503.
