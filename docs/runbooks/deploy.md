# Deploying with Argo CD

Phase 0 ships the structure. Phase 7 completes it with ExternalSecrets, ingress, TLS, OpenBao Kubernetes auth, backups and load tests.

- `deploy/helm/veyntora-service`: one hardened chart per service (non-root, read-only root filesystem, dropped capabilities, default-deny NetworkPolicy). `values/<env>/<service>.yaml` sets image, command, replicas and allowed callers.
- `deploy/argocd/project.yaml` + `root-<env>.yaml`: app of apps. **dev** syncs automatically. **staging** and **prod** sync manually after approval.
- Migrations: the `api` release runs `veyntora-api bootstrap` as an Argo CD **PreSync** hook. A failing migration stops the sync.
- CI pushes images tagged with the commit SHA to GHCR on `main`. Promotion means setting `image.tag` in the target environment's values (Phase 7 automates the dev bump).

```bash
kubectl apply -n argocd -f deploy/argocd/project.yaml
kubectl apply -n argocd -f deploy/argocd/root-dev.yaml
```
