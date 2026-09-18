package v1alpha1

import metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

// Hand-maintained supplement to zz_generated.deepcopy.go: controller-gen
// v0.22.0 (under Go 1.27 in this repo's toolchain) correctly determines
// that SaltMinionKeyStatus needs a DeepCopyInto (it emits the call site
// `in.Status.DeepCopyInto(&out.Status)` inside SaltMinionKey's own
// generated method) but does not actually emit SaltMinionKeyStatus's own
// method body - confirmed reproducible even with Conditions reduced to a
// plain []string, so it isn't specific to metav1.Condition. Filed as a
// known generator limitation in this environment; kept here rather than in
// the generated file so `make generate`/`controller-gen object` re-runs
// don't need to remember to restore it, and don't silently overwrite it
// either (this file's name doesn't match the generated one).
//
// If a future controller-gen/Go toolchain combination fixes this, this
// file becomes redundant (identical output) rather than incorrect - safe
// to delete once confirmed.

// DeepCopyInto is a deepcopy function, copying the receiver, writing into out. in must be non-nil.
func (in *SaltMinionKeyStatus) DeepCopyInto(out *SaltMinionKeyStatus) {
	*out = *in
	if in.Conditions != nil {
		in, out := &in.Conditions, &out.Conditions
		*out = make([]metav1.Condition, len(*in))
		for i := range *in {
			(*in)[i].DeepCopyInto(&(*out)[i])
		}
	}
}

// DeepCopy is a deepcopy function, copying the receiver, creating a new SaltMinionKeyStatus.
func (in *SaltMinionKeyStatus) DeepCopy() *SaltMinionKeyStatus {
	if in == nil {
		return nil
	}
	out := new(SaltMinionKeyStatus)
	in.DeepCopyInto(out)
	return out
}
