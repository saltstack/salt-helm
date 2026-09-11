# CI Debug Shortcut

When a GitHub Actions workflow fails, follow this checklist to reproduce the error locally and apply fixes.

## Checklist
1. **Identify the failing job** – Open the Actions run, locate the job name (e.g., `helm`).
2. **Pull the latest code** on your local machine:
   ```bash
   git fetch origin && git checkout <branch>
   ```
3. **Run the same steps locally**:
   - For Helm lint:
     ```bash
     helm lint ./salt-master-kubernetes
     ```
   - For Dockerfile lint:
     ```bash
     hadolint docker/salt-master/Dockerfile
     ```
4. **Inspect the error output** – Note line numbers and offending files.
5. **Fix the issue** – Edit the source file, then run the lint step again to ensure it passes.
6. **Commit & push** the fix:
   ```bash
   git add <changed-files>
   git commit -m "Fix <issue description>"
   git push
   ```
7. **Verify the CI** – The workflow will re‑run automatically; confirm that the job now succeeds.

**Tip:** When the failure is due to YAML parsing (e.g., Helm templates), use `helm template --debug` to get a full rendering and pinpoint the problematic lines.
