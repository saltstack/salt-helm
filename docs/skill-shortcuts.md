# Skill Shortcut Reference

This repository includes a set of **markdown skill files** that you can refer to when assigning complex or multi‑step tasks to the AI.  Each file provides a concise checklist or template that the assistant can follow without having to write custom scripts.

## Available skill shortcuts

- **`helm-test.md`** – Steps to build Docker images, push them to the local Harbor registry, and install the Helm chart on a real Kubernetes cluster.
- **`ci‑debug.md`** – How to reproduce CI failures locally, inspect lint errors, and apply quick fixes.
- **`release‑prep.md`** – Checklist for preparing a release: bump version, build/push images, package charts, and create a GitHub release.

## Using a skill shortcut

When you want the assistant to perform a complex workflow, you can reference the markdown file directly in your request, e.g.: 

```
Please run the steps described in **docs/helm-test.md** on the remote cluster.
```

The assistant will read the file, execute the outlined commands, and report back with results.

## Adding a new shortcut

1. Create a new `*.md` file under `docs/`.
2. Include a clear title, a numbered list of actions, and any required parameters.
3. Commit the file – the assistant will automatically be able to reference it.

---
*These shortcuts are intended to keep the repository clean (no executable scripts) while still providing reproducible, documented workflows.*
