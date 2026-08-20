#!/bin/sh
set -eu

result="$(salt-call --out=newline_values_only --retcode-passthrough status.master 2>/dev/null || true)"
case "$result" in
  *True*|*true*) exit 0 ;;
  *) exit 1 ;;
esac
