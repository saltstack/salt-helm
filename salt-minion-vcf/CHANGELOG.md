# Changelog (salt-minion-vcf image)

Records what each `salt-minion-vcf-image/vX.Y.Z` release tag (see
[`docs/releasing.md`](../docs/releasing.md)) actually carries. The tag itself is an independent
semver for this image — it does not encode the Salt or extension versions, so check here before
assuming.

## salt-minion-vcf-image/v0.1.0
- Salt: 3008.2
- Extensions: saltext.vcf[all]==1.0.0, saltext.vault==1.8.0, saltext.bmc==0.0.1, saltext.kubernetes==2.1.0
- Base: ubuntu:24.04
