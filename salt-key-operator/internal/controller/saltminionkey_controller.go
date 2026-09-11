// Package controller implements the reconcile loop for SaltMinionKey.
package controller

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/util/retry"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"

	saltv1alpha1 "github.com/saltstack/salt-helm/salt-key-operator/api/v1alpha1"
)

// SaltMinionKeyReconciler reconciles a SaltMinionKey object.
type SaltMinionKeyReconciler struct {
	client.Client
}

// trustedMinionsLabel marks the ConfigMap this controller writes into -
// applied by the salt-master-kubernetes chart's own templates/configmap.yaml
// (rendered with no `data:` key, specifically so Helm's 3-way merge never
// stomps this controller's out-of-band writes on `helm upgrade`). The
// controller finds its target by this label within a SaltMinionKey's own
// namespace, rather than the SaltMinionKey needing to name it explicitly -
// matching this repo's convention of one salt-master-kubernetes release per
// dedicated namespace (e.g. "salt-master").
const trustedMinionsLabel = "salt.saltstack.io/trusted-minions"

// +kubebuilder:rbac:groups=salt.saltstack.io,resources=saltminionkeys,verbs=get;list;watch;update;patch
// +kubebuilder:rbac:groups=salt.saltstack.io,resources=saltminionkeys/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=salt.saltstack.io,resources=saltminionkeys/finalizers,verbs=update
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch

// Reconcile implements the core loop: given a SaltMinionKey, find the one
// trusted-minions ConfigMap in its namespace and make sure spec.publicKey is
// present under data[spec.minionId] - or, on delete, make sure it's removed
// - and nothing else. It deliberately never touches the master pods
// directly: propagation from the ConfigMap into each replica's
// /etc/salt/pki/master/minions happens via the normal kubelet
// ConfigMap-volume sync, which the salt-master-kubernetes chart wires up
// (see its templates/statefulset.yaml, agent.trustedMinions.*).
func (r *SaltMinionKeyReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	var key saltv1alpha1.SaltMinionKey
	if err := r.Get(ctx, req.NamespacedName, &key); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, fmt.Errorf("getting SaltMinionKey: %w", err)
	}

	if !key.DeletionTimestamp.IsZero() {
		return r.reconcileDelete(ctx, &key)
	}

	if !controllerutil.ContainsFinalizer(&key, saltv1alpha1.Finalizer) {
		controllerutil.AddFinalizer(&key, saltv1alpha1.Finalizer)
		if err := r.Update(ctx, &key); err != nil {
			return ctrl.Result{}, fmt.Errorf("adding finalizer: %w", err)
		}
		// Re-fetch on the next reconcile triggered by this Update, rather
		// than continuing with a ResourceVersion that's now stale.
		return ctrl.Result{}, nil
	}

	cmName, err := r.findTrustedMinionsConfigMap(ctx, key.Namespace)
	if err != nil {
		r.setAccepted(ctx, &key, metav1.ConditionFalse, "NoMasterConfigMap", err.Error())
		return ctrl.Result{}, err
	}
	cmRef := types.NamespacedName{Namespace: key.Namespace, Name: cmName}

	if err := r.upsertKey(ctx, cmRef, key.Spec.MinionID, key.Spec.PublicKey); err != nil {
		r.setAccepted(ctx, &key, metav1.ConditionFalse, "ConfigMapWriteFailed", err.Error())
		return ctrl.Result{}, err
	}

	logger.Info("wrote minion public key into target master ConfigMap",
		"minionId", key.Spec.MinionID, "configMap", cmRef.String())

	key.Status.ObservedMasterConfigMap = cmName
	r.setAccepted(ctx, &key, metav1.ConditionTrue, "KeySeeded",
		fmt.Sprintf("public key written to configmap/%s data[%s]", cmName, key.Spec.MinionID))

	return ctrl.Result{}, nil
}

// findTrustedMinionsConfigMap looks up the one ConfigMap in the given
// namespace labeled trustedMinionsLabel=true - the one
// salt-master-kubernetes's own chart creates for its release. Returns an
// error if there's none yet (the master chart may not be installed, or not
// with agent.trustedMinions.enabled) or more than one (ambiguous - this
// repo's convention is one salt-master-kubernetes release per namespace;
// running more than one in the same namespace isn't supported by this
// auto-discovery).
func (r *SaltMinionKeyReconciler) findTrustedMinionsConfigMap(ctx context.Context, namespace string) (string, error) {
	var list corev1.ConfigMapList
	if err := r.List(ctx, &list, client.InNamespace(namespace), client.MatchingLabels{trustedMinionsLabel: "true"}); err != nil {
		return "", fmt.Errorf("listing trusted-minions configmaps in namespace %q: %w", namespace, err)
	}
	switch len(list.Items) {
	case 0:
		return "", fmt.Errorf("no ConfigMap labeled %s=true found in namespace %q - is salt-master-kubernetes installed there with agent.trustedMinions.enabled=true?", trustedMinionsLabel, namespace)
	case 1:
		return list.Items[0].Name, nil
	default:
		return "", fmt.Errorf("found %d ConfigMaps labeled %s=true in namespace %q, expected exactly 1 - this auto-discovery supports only one salt-master-kubernetes release per namespace", len(list.Items), trustedMinionsLabel, namespace)
	}
}

// reconcileDelete removes this minion's entry from the target ConfigMap
// (best-effort - if the ConfigMap can no longer be found at all, there's
// nothing left to clean up) and then drops the finalizer so the object can
// actually be removed from etcd.
func (r *SaltMinionKeyReconciler) reconcileDelete(ctx context.Context, key *saltv1alpha1.SaltMinionKey) (ctrl.Result, error) {
	if !controllerutil.ContainsFinalizer(key, saltv1alpha1.Finalizer) {
		return ctrl.Result{}, nil
	}

	cmName, findErr := r.findTrustedMinionsConfigMap(ctx, key.Namespace)
	if findErr == nil {
		cmRef := types.NamespacedName{Namespace: key.Namespace, Name: cmName}
		err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
			var cm corev1.ConfigMap
			if getErr := r.Get(ctx, cmRef, &cm); getErr != nil {
				if apierrors.IsNotFound(getErr) {
					return nil
				}
				return getErr
			}
			if cm.Data == nil {
				return nil
			}
			if _, ok := cm.Data[key.Spec.MinionID]; !ok {
				return nil
			}
			delete(cm.Data, key.Spec.MinionID)
			return r.Update(ctx, &cm)
		})
		if err != nil {
			return ctrl.Result{}, fmt.Errorf("removing minion key from configmap/%s: %w", cmRef.Name, err)
		}
	}
	// findErr != nil (no target ConfigMap found at all, or ambiguous) is not
	// treated as blocking cleanup - there's nothing unambiguous to remove
	// the key from, and refusing to drop the finalizer over it would leave
	// the SaltMinionKey stuck deleting forever.

	controllerutil.RemoveFinalizer(key, saltv1alpha1.Finalizer)
	if err := r.Update(ctx, key); err != nil {
		return ctrl.Result{}, fmt.Errorf("removing finalizer: %w", err)
	}
	return ctrl.Result{}, nil
}

// upsertKey writes data[minionID] = pubKeyPEM into the named ConfigMap,
// retrying on write conflicts. This is the concrete payoff of using
// controller-runtime/client-go here rather than a script-based
// `kubectl patch` loop: many SaltMinionKey objects can reconcile
// concurrently against the same target ConfigMap (e.g. on operator startup,
// reconciling every existing CR at once), and RetryOnConflict's
// optimistic-concurrency retry is what keeps concurrent writers from
// silently dropping each other's updates. The ConfigMap itself is always
// expected to already exist (created by salt-master-kubernetes's own
// chart) - this does not create one, since findTrustedMinionsConfigMap
// already requires exactly one to exist before this is ever called.
func (r *SaltMinionKeyReconciler) upsertKey(ctx context.Context, cmRef types.NamespacedName, minionID, pubKeyPEM string) error {
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		var cm corev1.ConfigMap
		if err := r.Get(ctx, cmRef, &cm); err != nil {
			return err
		}
		if cm.Data != nil && cm.Data[minionID] == pubKeyPEM {
			return nil // already up to date, no write needed
		}
		if cm.Data == nil {
			cm.Data = map[string]string{}
		}
		cm.Data[minionID] = pubKeyPEM
		return r.Update(ctx, &cm)
	})
}

// setAccepted patches status.conditions[type=Accepted] and swallows (but
// logs) any error updating status itself, since a status-update failure
// shouldn't mask the underlying reconcile error being returned to the
// caller.
func (r *SaltMinionKeyReconciler) setAccepted(ctx context.Context, key *saltv1alpha1.SaltMinionKey, status metav1.ConditionStatus, reason, message string) {
	meta.SetStatusCondition(&key.Status.Conditions, metav1.Condition{
		Type:               saltv1alpha1.ConditionTypeAccepted,
		Status:             status,
		Reason:             reason,
		Message:            message,
		ObservedGeneration: key.Generation,
	})
	if err := r.Status().Update(ctx, key); err != nil {
		log.FromContext(ctx).Error(err, "failed to update SaltMinionKey status")
	}
}

// SetupWithManager registers this reconciler, plus a secondary watch on
// ConfigMaps carrying trustedMinionsLabel - so a salt-master-kubernetes
// chart installed *after* some SaltMinionKey objects already exist (which
// would otherwise be stuck in a NoMasterConfigMap state) gets picked up as
// soon as its ConfigMap appears, without waiting for the next unrelated
// change to those SaltMinionKey objects.
func (r *SaltMinionKeyReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&saltv1alpha1.SaltMinionKey{}).
		Watches(
			&corev1.ConfigMap{},
			handler.EnqueueRequestsFromMapFunc(r.findKeysForConfigMap(mgr)),
		).
		Complete(r)
}

func (r *SaltMinionKeyReconciler) findKeysForConfigMap(mgr ctrl.Manager) handler.MapFunc {
	return func(ctx context.Context, obj client.Object) []ctrl.Request {
		if obj.GetLabels()[trustedMinionsLabel] != "true" {
			return nil
		}
		var list saltv1alpha1.SaltMinionKeyList
		if err := mgr.GetClient().List(ctx, &list, client.InNamespace(obj.GetNamespace())); err != nil {
			return nil
		}
		reqs := make([]ctrl.Request, 0, len(list.Items))
		for _, k := range list.Items {
			reqs = append(reqs, ctrl.Request{NamespacedName: types.NamespacedName{Namespace: k.Namespace, Name: k.Name}})
		}
		return reqs
	}
}
