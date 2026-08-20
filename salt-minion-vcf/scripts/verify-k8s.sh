#!/bin/sh
set -eu

NAMESPACE="${NAMESPACE:-vcf-salt}"
SELECTOR="${SELECTOR:-app.kubernetes.io/name=salt-minion-vcf}"

echo "Pods:"
kubectl -n "$NAMESPACE" get pods -l "$SELECTOR" -o wide

POD="$(kubectl -n "$NAMESPACE" get pod -l "$SELECTOR" -o jsonpath='{.items[0].metadata.name}')"

echo
echo "Selected pod: $POD"
kubectl -n "$NAMESPACE" exec "$POD" -- salt-call --local test.version
kubectl -n "$NAMESPACE" exec "$POD" -- salt-call --local test.ping

echo
echo "Master status (becomes true after key acceptance):"
kubectl -n "$NAMESPACE" exec "$POD" -- salt-call status.master || true
