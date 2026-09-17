# Release Preparation Checklist

Use this guide to prepare a new release of the `salt-kubernetes` charts and container images.

## 1. Version bump
- Update `Chart.yaml` in each chart directory (`salt-master-kubernetes`, `salt-minion-kubernetes`, `salt-minion-vcf/helm/salt-minion-vcf`).
- Update the image tags in the Helm `values.yaml` files if you are pinning a new version.
- Commit the changes with a message like `chore: bump version to 1.2.3`.

## 2. Build & push images
```bash
# Example for the master image
docker build -t salt-master:1.2.3 docker/salt-master
docker tag salt-master:1.2.3 ghcr.io/saltstack/salt-kubernetes/salt-master:1.2.3
docker push ghcr.io/saltstack/salt-kubernetes/salt-master:1.2.3
```
Repeat for `salt-minion-kubernetes` and `salt-minion-vcf`.

## 3. Package Helm charts
```bash
helm package salt-master-kubernetes
helm package salt-minion-kubernetes
helm package salt-minion-vcf/helm/salt-minion-vcf
```
The resulting `.tgz` files can be uploaded to a chart repository or GitHub Releases.

## 4. Create a GitHub release
- Draft a new release on GitHub, tag it with the new version (e.g., `v1.2.3`).
- Attach the packaged chart `.tgz` files.
- Include a changelog summary (you can copy from `CHANGELOG.md`).

## 5. Verify the release
- Install the charts from the release assets on a test cluster.
- Run basic sanity checks (e.g., `helm test` if tests are defined).

## 6. Post‑release tasks
- Update the documentation (`README.md`, `docs/*.md`) to reference the new version.
- Announce the release to the relevant channels.

You can ask the assistant to **execute the steps in `docs/release-prep.md`** for a guided release process.
