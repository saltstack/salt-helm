# Changelog (salt-key-operator image)

Records what each `salt-key-operator-image/vX.Y.Z` release tag (see
[`docs/releasing.md`](../docs/releasing.md)) actually carries.

## salt-key-operator-image/v0.1.0
- Initial release: `SaltMinionKey` (`salt.saltstack.io/v1alpha1`) controller,
  reconciling into a target `salt-master-kubernetes` release's
  trusted-minions ConfigMap. Deliberately minimal CRD (just `minionId` +
  inline `publicKey` - no Secret reference, no explicit target reference;
  the controller auto-discovers the one trusted-minions ConfigMap in its
  own namespace). See `README.md` for the full design.
- Go 1.27, controller-runtime v0.25.0.
- Distroless `static-debian12:nonroot` runtime image (uid/gid 65532, no
  shell, no package manager).
