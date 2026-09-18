package controller

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	saltv1alpha1 "github.com/saltstack/salt-kubernetes/salt-key-operator/api/v1alpha1"
)

const testPubKeyPEM = "-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----\n"

func newScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	if err := saltv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	return scheme
}

func newFakeReconciler(t *testing.T, objs ...client.Object) (*SaltMinionKeyReconciler, client.Client) {
	t.Helper()
	c := fake.NewClientBuilder().
		WithScheme(newScheme(t)).
		WithObjects(objs...).
		WithStatusSubresource(&saltv1alpha1.SaltMinionKey{}).
		Build()
	return &SaltMinionKeyReconciler{Client: c}, c
}

// trustedMinionsConfigMap mimics what salt-master-kubernetes's own chart
// creates: labeled, but with no data - matching the "render no `data:` key
// at all" trick that keeps `helm upgrade` from stomping the operator's
// out-of-band writes.
func trustedMinionsConfigMap(name, namespace string) *corev1.ConfigMap {
	return &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			Labels:    map[string]string{trustedMinionsLabel: "true"},
		},
	}
}

func testKey(name, namespace, minionID string) *saltv1alpha1.SaltMinionKey {
	return &saltv1alpha1.SaltMinionKey{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Spec: saltv1alpha1.SaltMinionKeySpec{
			MinionID:  minionID,
			PublicKey: testPubKeyPEM,
		},
	}
}

// TestReconcile_CreatesConfigMapAndAcceptsKey covers the primary happy path:
// a brand-new SaltMinionKey, with exactly one trusted-minions ConfigMap
// already present in its namespace, should end up with the finalizer set,
// the ConfigMap's data[minionId] set to the inline public key, and
// status.conditions[Accepted]=True.
func TestReconcile_CreatesConfigMapAndAcceptsKey(t *testing.T) {
	ns := "salt-master"
	cm := trustedMinionsConfigMap("trusted-minions", ns)
	key := testKey("minion-a", ns, "minion-a")

	r, c := newFakeReconciler(t, cm, key)
	ctx := context.Background()
	req := ctrl.Request{NamespacedName: types.NamespacedName{Namespace: ns, Name: "minion-a"}}

	// First reconcile only adds the finalizer (see Reconcile's early return
	// after Update) - matches real controller-runtime behavior, where that
	// Update triggers a fresh reconcile rather than continuing with a
	// stale object.
	if _, err := r.Reconcile(ctx, req); err != nil {
		t.Fatalf("first reconcile (finalizer): %v", err)
	}
	if _, err := r.Reconcile(ctx, req); err != nil {
		t.Fatalf("second reconcile (key seeding): %v", err)
	}

	var got corev1.ConfigMap
	if err := c.Get(ctx, types.NamespacedName{Namespace: ns, Name: "trusted-minions"}, &got); err != nil {
		t.Fatalf("get configmap: %v", err)
	}
	if data := got.Data["minion-a"]; data != testPubKeyPEM {
		t.Fatalf("configmap data[minion-a] = %q, want %q", data, testPubKeyPEM)
	}

	var updated saltv1alpha1.SaltMinionKey
	if err := c.Get(ctx, req.NamespacedName, &updated); err != nil {
		t.Fatalf("get SaltMinionKey: %v", err)
	}
	found := false
	for _, cond := range updated.Status.Conditions {
		if cond.Type == saltv1alpha1.ConditionTypeAccepted && cond.Status == metav1.ConditionTrue {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected Accepted=True condition, got %+v", updated.Status.Conditions)
	}
	if updated.Status.ObservedMasterConfigMap != "trusted-minions" {
		t.Fatalf("observedMasterConfigMap = %q, want trusted-minions", updated.Status.ObservedMasterConfigMap)
	}
}

// TestReconcile_MultipleKeysShareOneConfigMap exercises the concurrent-write
// path this design specifically relies on client-go's RetryOnConflict for:
// two different SaltMinionKey objects in the same namespace should both end
// up present in the one discovered ConfigMap, not have one silently
// clobber the other.
func TestReconcile_MultipleKeysShareOneConfigMap(t *testing.T) {
	ns := "salt-master"
	cm := trustedMinionsConfigMap("trusted-minions", ns)
	keyA := testKey("minion-a", ns, "minion-a")
	keyB := testKey("minion-b", ns, "minion-b")

	r, c := newFakeReconciler(t, cm, keyA, keyB)
	ctx := context.Background()

	for _, name := range []string{"minion-a", "minion-b"} {
		req := ctrl.Request{NamespacedName: types.NamespacedName{Namespace: ns, Name: name}}
		if _, err := r.Reconcile(ctx, req); err != nil { // add finalizer
			t.Fatalf("reconcile %s (finalizer): %v", name, err)
		}
		if _, err := r.Reconcile(ctx, req); err != nil { // seed key
			t.Fatalf("reconcile %s (seed): %v", name, err)
		}
	}

	var got corev1.ConfigMap
	if err := c.Get(ctx, types.NamespacedName{Namespace: ns, Name: "trusted-minions"}, &got); err != nil {
		t.Fatalf("get configmap: %v", err)
	}
	if len(got.Data) != 2 || got.Data["minion-a"] == "" || got.Data["minion-b"] == "" {
		t.Fatalf("expected both minion-a and minion-b present, got %+v", got.Data)
	}
}

// TestReconcile_NoTrustedMinionsConfigMap covers the "master chart not
// installed yet (or not with agent.trustedMinions.enabled)" case: reconcile
// should return an error and set Accepted=False, not silently succeed or
// panic.
func TestReconcile_NoTrustedMinionsConfigMap(t *testing.T) {
	ns := "salt-master"
	key := testKey("minion-a", ns, "minion-a")

	r, c := newFakeReconciler(t, key)
	ctx := context.Background()
	req := ctrl.Request{NamespacedName: types.NamespacedName{Namespace: ns, Name: "minion-a"}}

	if _, err := r.Reconcile(ctx, req); err != nil {
		t.Fatalf("reconcile (finalizer): %v", err)
	}
	if _, err := r.Reconcile(ctx, req); err == nil {
		t.Fatal("expected an error when no trusted-minions ConfigMap exists yet")
	}

	var updated saltv1alpha1.SaltMinionKey
	if err := c.Get(ctx, req.NamespacedName, &updated); err != nil {
		t.Fatalf("get SaltMinionKey: %v", err)
	}
	for _, cond := range updated.Status.Conditions {
		if cond.Type == saltv1alpha1.ConditionTypeAccepted && cond.Status != metav1.ConditionFalse {
			t.Fatalf("expected Accepted=False, got %+v", cond)
		}
	}
}

// TestReconcile_DeleteRemovesKeyAndFinalizer covers cleanup: deleting a
// SaltMinionKey that already seeded a ConfigMap entry should remove that
// entry and let the finalizer be dropped so the object actually disappears.
func TestReconcile_DeleteRemovesKeyAndFinalizer(t *testing.T) {
	ns := "salt-master"
	cm := trustedMinionsConfigMap("trusted-minions", ns)
	key := testKey("minion-a", ns, "minion-a")

	r, c := newFakeReconciler(t, cm, key)
	ctx := context.Background()
	req := ctrl.Request{NamespacedName: types.NamespacedName{Namespace: ns, Name: "minion-a"}}

	if _, err := r.Reconcile(ctx, req); err != nil {
		t.Fatalf("reconcile (finalizer): %v", err)
	}
	if _, err := r.Reconcile(ctx, req); err != nil {
		t.Fatalf("reconcile (seed): %v", err)
	}

	if err := c.Delete(ctx, key); err != nil {
		t.Fatalf("delete SaltMinionKey: %v", err)
	}
	if _, err := r.Reconcile(ctx, req); err != nil {
		t.Fatalf("reconcile (delete cleanup): %v", err)
	}

	var got corev1.ConfigMap
	if err := c.Get(ctx, types.NamespacedName{Namespace: ns, Name: "trusted-minions"}, &got); err != nil {
		t.Fatalf("get configmap: %v", err)
	}
	if _, ok := got.Data["minion-a"]; ok {
		t.Fatalf("expected minion-a to be removed from configmap data, got %+v", got.Data)
	}

	var gone saltv1alpha1.SaltMinionKey
	err := c.Get(ctx, req.NamespacedName, &gone)
	if !apierrors.IsNotFound(err) {
		t.Fatalf("expected SaltMinionKey to be gone after finalizer removal, got err=%v", err)
	}
}
