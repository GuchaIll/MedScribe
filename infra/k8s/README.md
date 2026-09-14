# MedScribe Kubernetes Manifests

The Go gateway and its Kafka consumer proxies are built as **one image** that
runs in different modes (`--mode=…`, see `services/api/internal/app`). In
production they deploy as **separate Deployments** so each scales independently;
locally (`docker compose`) the same binary runs in `--mode=all` as a single
process.

## Topology

| Deployment | Mode | Consumes | Proxies to | Scales on |
|---|---|---|---|---|
| `medscribe-gateway` | `gateway` | — (HTTP only) | — | CPU (HPA) |
| `medscribe-pipeline-worker` | `pipeline-worker` | `pipeline.trigger` | Python pipeline | Kafka lag (KEDA) |
| `medscribe-ocr-worker` | `ocr-worker` | `ocr.jobs` | Python OCR | Kafka lag (KEDA) |
| `medscribe-audio-worker` | `audio-worker` | `audio.ingest` | Modal speech worker | Kafka lag (KEDA) |

All four run the same image (`ghcr.io/medscribe/api:<tag>`); only the `--mode`
arg differs. Gateway exposes `/health`; workers expose `/health`, `/healthz`,
`/readyz`, and `/metrics`.

## Prerequisites

- Postgres, Redis, and Kafka reachable at the hostnames in `base/configmap.yaml`
  (`postgres`, `redis`, `kafka`) — bring your own or add manifests.
- [KEDA](https://keda.sh) installed for the worker `ScaledObject`s.
- An NGINX ingress controller for `services/api/ingress.yaml`.

## Apply

```bash
kubectl apply -f base/namespace.yaml
# populate the real secret first (see base/secrets.yaml header), then:
kubectl apply -f base/configmap.yaml -f base/secrets.yaml
kubectl apply -R -f services/
```

## Notes

- `base/secrets.yaml` ships placeholder values — replace via your secret
  manager; never commit real credentials.
- Pin `image:` to a real tag instead of `latest` before deploying.
- Speech inference itself runs on **Modal** (`infra/modal/`), not in-cluster;
  the audio worker only proxies to it over HTTP.
