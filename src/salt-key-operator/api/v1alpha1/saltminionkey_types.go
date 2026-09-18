package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ConditionTypeAccepted is the status condition type set on a SaltMinionKey
// once its public key has been written into the target master ConfigMap.
const ConditionTypeAccepted = "Accepted"

// Finalizer is set on every SaltMinionKey so the controller can remove the
// corresponding entry from the target ConfigMap before the object is
// actually deleted from etcd.
const Finalizer = "salt.saltstack.io/minion-key-cleanup"

// SaltMinionKeySpec declares that a specific minion ID's public key should
// be trusted (i.e. "accepted", in salt-key terms) by whichever
// salt-master-kubernetes release lives in this SaltMinionKey's own
// namespace, without ever running `salt-key -a` by hand.
//
// Deliberately minimal - just the two facts that actually vary per minion.
// There's no reference to a Secret (a minion's public key isn't sensitive -
// it's the whole point of asymmetric crypto that the public half is safe to
// hand out, so requiring a separate Secret object just to hold it would be
// pure indirection) and no reference to which master ConfigMap to target
// (the controller discovers it by label within this object's own
// namespace - see internal/controller - matching this repo's existing
// convention of one salt-master-kubernetes release per dedicated
// namespace, e.g. "salt-master").
type SaltMinionKeySpec struct {
	// MinionID is the exact Salt minion ID - this becomes the filename
	// under the target master's /etc/salt/pki/master/minions/ once
	// trusted. Kept distinct from metadata.name because minion IDs may
	// contain characters (uppercase, underscores, dots, colons - e.g. an
	// FQDN) that are not valid Kubernetes object names (RFC 1123).
	// +kubebuilder:validation:MinLength=1
	MinionID string `json:"minionId"`

	// PublicKey is the minion's public key, PEM-encoded
	// ("-----BEGIN PUBLIC KEY-----..."), inline. Not sensitive - see the
	// type-level comment above for why this isn't a SecretRef.
	// +kubebuilder:validation:MinLength=1
	PublicKey string `json:"publicKey"`
}

// SaltMinionKeyStatus reports whether the key has actually been written
// into the target master ConfigMap yet.
type SaltMinionKeyStatus struct {
	// Conditions represent the latest available observations of this
	// SaltMinionKey's state. See ConditionTypeAccepted.
	// +patchMergeKey=type
	// +patchStrategy=merge
	// +listType=map
	// +listMapKey=type
	Conditions []metav1.Condition `json:"conditions,omitempty" patchStrategy:"merge" patchMergeKey:"type"`

	// ObservedMasterConfigMap is the trusted-minions ConfigMap this key was
	// last successfully written to - the name the controller auto-discovered
	// in this object's own namespace, surfaced here so a status reader
	// doesn't have to go looking for it themselves.
	ObservedMasterConfigMap string `json:"observedMasterConfigMap,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Minion",type=string,JSONPath=`.spec.minionId`
// +kubebuilder:printcolumn:name="ConfigMap",type=string,JSONPath=`.status.observedMasterConfigMap`
// +kubebuilder:printcolumn:name="Accepted",type=string,JSONPath=`.status.conditions[?(@.type=="Accepted")].status`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// SaltMinionKey is the Schema for the saltminionkeys API. Creating one is
// the declarative replacement for running `salt-key -a <minionId>` on a
// salt-master-kubernetes pod - and unlike a manual salt-key -a (which only
// ever affects whichever single pod `kubectl exec` happens to pick), the
// controller for this resource writes into a ConfigMap mounted into every
// replica of the target master release, so acceptance is consistent across
// an active-active master tier.
type SaltMinionKey struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   SaltMinionKeySpec   `json:"spec"`
	Status SaltMinionKeyStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// SaltMinionKeyList contains a list of SaltMinionKey.
type SaltMinionKeyList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []SaltMinionKey `json:"items"`
}

func init() {
	SchemeBuilder.Register(&SaltMinionKey{}, &SaltMinionKeyList{})
}
