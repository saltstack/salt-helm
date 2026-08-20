# Security

- Never bake customer VCF credentials into the image.
- Never put VCF credentials in a Kubernetes ConfigMap - use a Secret (see
  README.md § Pillar Data for saltext.vcf Credentials).
- Prefer Salt Pillar or an approved secret manager for endpoint credentials.
- Only `*.sls.example` files under `pillar/` are tracked; real `*.sls` files
  are gitignored - never force-add or commit them.
- Local pillar (`/etc/salt/pillar` in this container) only affects
  `salt-call --local`; jobs dispatched from a real Salt Master use the
  Master's own pillar_roots and never see this container's local files -
  unless `SALT_FILE_CLIENT_LOCAL=true` is set, which is unverified beyond
  basic testing (see README.md § Vault Integration before relying on it).
- Prefer `VAULT_SECRET_ID_FILE`/`VAULT_TOKEN_FILE` (mounted secret) over the
  plain `VAULT_SECRET_ID`/`VAULT_TOKEN` env vars, which are visible via
  `docker inspect`/`kubectl get pod -o yaml`.
- Even with `saltext.vault`'s Master-broker pattern, the Master still
  renders pillar (and thus transiently handles the secret value) unless
  pillar is rendered on the minion - see README.md § Vault Integration.
- Persist `/etc/salt/pki/minion`.
- Configure `master_finger` for trusted first contact.
- Do not run privileged. The image runs as a dedicated non-root user (uid/gid `10000`); Kubernetes/Helm set matching `runAsUser`/`runAsGroup`/`fsGroup`.
- Do not mount the host root filesystem.
- Do not mount `/var/run/docker.sock`.
- Keep TLS verification enabled for VCF endpoints.
- Use customer CA bundles rather than disabling certificate verification.
- Restrict network egress to required Salt Master and VCF management endpoints.
- Treat grains as metadata/targeting information, not as an authorization boundary.
