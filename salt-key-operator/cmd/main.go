// +kubebuilder:rbac:groups=coordination.k8s.io,resources=leases,verbs=get;list;watch;create;update;patch

// Command salt-key-operator runs the controller-manager for the
// SaltMinionKey CRD - the declarative replacement for running
// `salt-key -a <minionId>` by hand against a salt-master-kubernetes pod.
// See salt-key-operator/README.md and salt-master-kubernetes's own
// agent.trustedMinions.* values for how the two sides connect.
package main

import (
	"flag"
	"os"

	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"

	saltv1alpha1 "github.com/saltstack/salt-helm/salt-key-operator/api/v1alpha1"
	"github.com/saltstack/salt-helm/salt-key-operator/internal/controller"
)

var scheme = runtime.NewScheme()

func init() {
	_ = clientgoscheme.AddToScheme(scheme)
	_ = saltv1alpha1.AddToScheme(scheme)
}

func main() {
	var metricsAddr string
	var probeAddr string
	var enableLeaderElection bool
	var watchNamespace string

	flag.StringVar(&metricsAddr, "metrics-bind-address", ":8443", "The address the metrics endpoint binds to.")
	flag.StringVar(&probeAddr, "health-probe-bind-address", ":8081", "The address the health probe endpoint binds to.")
	flag.BoolVar(&enableLeaderElection, "leader-elect", false,
		"Enable leader election so the operator can run with more than one replica without concurrent writers racing on the same ConfigMap.")
	flag.StringVar(&watchNamespace, "namespace", "",
		"Restrict watches/RBAC to a single namespace. Leave empty (the default) to watch cluster-wide - see README.md for the trade-off.")

	opts := zap.Options{Development: false}
	opts.BindFlags(flag.CommandLine)
	flag.Parse()

	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

	mgrOpts := ctrl.Options{
		Scheme:                 scheme,
		Metrics:                metricsserver.Options{BindAddress: metricsAddr},
		HealthProbeBindAddress: probeAddr,
		LeaderElection:         enableLeaderElection,
		LeaderElectionID:       "salt-key-operator-leader-election",
	}
	if watchNamespace != "" {
		mgrOpts.Cache = cache.Options{
			DefaultNamespaces: map[string]cache.Config{watchNamespace: {}},
		}
	}

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), mgrOpts)
	if err != nil {
		ctrl.Log.Error(err, "unable to start manager")
		os.Exit(1)
	}

	if err := (&controller.SaltMinionKeyReconciler{Client: mgr.GetClient()}).SetupWithManager(mgr); err != nil {
		ctrl.Log.Error(err, "unable to create controller", "controller", "SaltMinionKey")
		os.Exit(1)
	}

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		ctrl.Log.Error(err, "unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		ctrl.Log.Error(err, "unable to set up ready check")
		os.Exit(1)
	}

	ctrl.Log.Info("starting manager")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		ctrl.Log.Error(err, "problem running manager")
		os.Exit(1)
	}
}
