#!/usr/bin/env python3
"""
vcf-ops-onboard.py

Interactive onboarding tool that brings up a salt-minion-vcf instance (Docker
or Kubernetes/Helm) and registers it as a trusted minion against a VCF
Operations-managed Salt master - with no private key ever leaving the minion,
and no VCF Operations credentials ever reaching the minion itself.

Flow:
  1. Prompt for VCF Operations (Suite API) connection details and log in.
  2. Resolve the Salt master governing a given VCF instance
     (GET /suite-api/api/salt/master?resourceId=<vcfInstanceId>).
  3. Compute the Salt-compatible master_finger from the returned master
     public key, so the minion can verify the master's identity on connect.
  4. Start the minion (docker run, or helm install/upgrade), pointed at the
     master and given a freshly generated minion ID. The minion generates
     its own RSA keypair locally on first start - this script never sees it.
  5. Read back the minion's public key (never the private key) and its ID.
  6. Trust that key against the master
     (POST /suite-api/api/salt/minions/{minionId}/trusted-keys).
  7. Poll the minion (already retrying in the background) until the master
     accepts it, using the exact check the image's own healthcheck/readiness
     probe uses: `salt-call status.master`.

Steps 4-7 can be repeated for multiple minions in one session without
re-entering VCF Operations credentials.

Every step is written to a timestamped log file (default:
vcf-ops-onboard-<timestamp>.log) in addition to the interactive console
output, for audit/troubleshooting. Passwords and auth tokens are never
logged.

Only two dependencies: Python 3.8+, and whichever of `docker`/`helm`+`kubectl`
you're deploying with. No third-party pip packages required.

Reference: https://github.com/saltstack/salt-helm/tree/main/salt-minion-vcf
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import logging
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional


LOG = logging.getLogger("vcf_onboard")

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

def setup_logging(log_file: str, verbose: bool) -> None:
    LOG.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    LOG.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("    . %(message)s"))
        LOG.addHandler(console_handler)


# --------------------------------------------------------------------------
# Console helpers (each also writes to the log file for audit purposes)
# --------------------------------------------------------------------------

def _supports_color() -> bool:
    return sys.stdout.isatty()


class _C:
    RESET = "\033[0m" if _supports_color() else ""
    BOLD = "\033[1m" if _supports_color() else ""
    GREEN = "\033[32m" if _supports_color() else ""
    RED = "\033[31m" if _supports_color() else ""
    YELLOW = "\033[33m" if _supports_color() else ""
    CYAN = "\033[36m" if _supports_color() else ""
    DIM = "\033[2m" if _supports_color() else ""


def step(n: int, total: int, title: str) -> None:
    bar = "=" * 70
    print(f"\n{_C.BOLD}{_C.CYAN}{bar}\n STEP {n}/{total}: {title}\n{bar}{_C.RESET}")
    LOG.info(f"==== STEP {n}/{total}: {title} ====")


def info(msg: str) -> None:
    print(f"  {msg}")
    LOG.info(msg)


def ok(msg: str) -> None:
    print(f"{_C.GREEN}[OK]{_C.RESET} {msg}")
    LOG.info(f"OK: {msg}")


def warn(msg: str) -> None:
    print(f"{_C.YELLOW}[WARN]{_C.RESET} {msg}")
    LOG.warning(msg)


def fail(msg: str) -> None:
    print(f"{_C.RED}[FAIL]{_C.RESET} {msg}")
    LOG.error(msg)


def die(msg: str, code: int = 1) -> None:
    fail(msg)
    sys.exit(code)


def prompt(text: str, default: Optional[str] = None, secret: bool = False,
           validate: Optional[Callable[[str], bool]] = None,
           validate_hint: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    reader = getpass.getpass if secret else input
    while True:
        value = reader(f"{text}{suffix}: ").strip()
        if not value and default is not None:
            value = default
        if not value:
            print("  (this value is required)")
            continue
        if validate and not validate(value):
            print(f"  Invalid value.{(' ' + validate_hint) if validate_hint else ''}")
            continue
        LOG.debug(f"prompt '{text}' -> {'<redacted>' if secret else value}")
        return value


def prompt_uuid(text: str, default: Optional[str] = None) -> str:
    return prompt(text, default=default, validate=lambda v: bool(UUID_RE.match(v)),
                  validate_hint="Expected a UUID, e.g. 3fa85f64-5717-4562-b3fc-2c963f66afa6")


def choose(text: str, options: list, default: Optional[str] = None) -> str:
    print(f"{text}")
    for i, opt in enumerate(options, 1):
        marker = " (default)" if opt == default else ""
        print(f"  {i}. {opt}{marker}")
    default_idx = str(options.index(default) + 1) if default in options else None
    while True:
        raw = prompt("Enter choice number", default=default_idx)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            choice = options[int(raw) - 1]
            LOG.debug(f"choice '{text}' -> {choice}")
            return choice
        print(f"  Please enter a number between 1 and {len(options)}")


def confirm(text: str, default: bool = True, assume_yes: bool = False) -> bool:
    if assume_yes:
        LOG.debug(f"confirm '{text}' -> yes (--yes)")
        return True
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input(f"{text} {suffix} ").strip().lower()
        if not raw:
            result = default
        elif raw in ("y", "yes"):
            result = True
        elif raw in ("n", "no"):
            result = False
        else:
            continue
        LOG.debug(f"confirm '{text}' -> {result}")
        return result


def print_summary(title: str, pairs: list) -> None:
    width = max([len(k) for k, _ in pairs] + [len(title)]) + 2
    print(f"\n{_C.BOLD}{title}{_C.RESET}")
    print(f"{_C.DIM}{'-' * 70}{_C.RESET}")
    for key, value in pairs:
        print(f"  {key:<{width}} {value}")
    print(f"{_C.DIM}{'-' * 70}{_C.RESET}")
    LOG.info(f"{title}: " + ", ".join(f"{k}={v}" for k, v in pairs))


class Spinner:
    """Animated progress indicator for interactive terminals; falls back to
    periodic plain-text lines when output isn't a TTY (e.g. redirected to a
    file), so progress is still visible either way."""

    FRAMES = "|/-\\"

    def __init__(self, message: str):
        self.message = message
        self._i = 0
        self.active = sys.stdout.isatty()

    def spin(self, extra: str = "") -> None:
        if not self.active:
            return
        frame = self.FRAMES[self._i % len(self.FRAMES)]
        self._i += 1
        suffix = f" - {extra}" if extra else ""
        sys.stdout.write(f"\r  {frame} {self.message}{suffix}" + " " * 10)
        sys.stdout.flush()

    def stop(self, final: Optional[str] = None) -> None:
        if self.active:
            sys.stdout.write("\r" + " " * 100 + "\r")
            sys.stdout.flush()
        if final:
            print(final)


def wait_until(predicate: Callable[[], bool], timeout: int, check_interval: float,
               message: str, dry_run: bool = False) -> bool:
    """Poll `predicate` at most once per check_interval until it returns True
    or timeout elapses. Animates a spinner (or prints periodically) while
    waiting; every check is logged to the audit log regardless."""
    if dry_run:
        LOG.info(f"(dry-run) skipping wait: {message}")
        return True

    spinner = Spinner(message)
    deadline = time.time() + timeout
    next_check = 0.0
    last_plain_print = 0.0

    while time.time() < deadline:
        now = time.time()
        if now >= next_check:
            result = predicate()
            LOG.debug(f"check '{message}' -> {result}")
            if result:
                spinner.stop()
                return True
            next_check = now + check_interval

        remaining = int(deadline - now)
        if spinner.active:
            spinner.spin(f"{remaining}s remaining")
            time.sleep(0.15)
        else:
            if now - last_plain_print >= check_interval:
                print(f"  {message}... ({remaining}s remaining)")
                last_plain_print = now
            time.sleep(check_interval)

    spinner.stop()
    return False


# --------------------------------------------------------------------------
# Shell command execution
# --------------------------------------------------------------------------

def run(cmd: list, dry_run: bool = False, capture: bool = False, check: bool = True) -> str:
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"  $ {printable}")
    LOG.debug(f"$ {printable}")
    if dry_run:
        return ""
    try:
        result = subprocess.run(
            cmd,
            check=check,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            text=True,
        )
    except FileNotFoundError:
        die(f"Command not found: {cmd[0]}. Is it installed and on PATH?")
    except subprocess.CalledProcessError as e:
        LOG.error(f"command failed (exit {e.returncode}): {printable}")
        raise
    if capture:
        output = (result.stdout or "").strip()
        LOG.debug(f"output: {output}")
        return output
    return ""


# --------------------------------------------------------------------------
# VCF Operations (Suite API) client
# --------------------------------------------------------------------------

class OpsApiError(Exception):
    pass


class OpsClient:
    """
    Thin client for the two VCF Operations Salt trust-management endpoints.

    Auth flow (matches the one already used by other internal tooling
    against this same backend):
        POST {base}/api/auth/token/acquire  {username, password} -> {token}
        Authorization: OpsToken <token>   (on every subsequent call)

    If your environment's login flow differs (e.g. CSP/SSO-fronted), adjust
    `login()` accordingly - everything else in this class is unaffected.
    """

    def __init__(self, host: str, username: str, password: str,
                 base_path: str = "/suite-api", verify_tls: bool = True, timeout: int = 30):
        self.base_url = f"https://{host}{base_path}"
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self.timeout = timeout
        self._token: Optional[str] = None
        self._ssl_context = ssl.create_default_context()
        if not verify_tls:
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE

    def _request(self, method: str, path: str, params: Optional[dict] = None,
                 json_body: Optional[dict] = None, authed: bool = True) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"

        LOG.debug(f"{method} {url}")

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if authed:
            if not self._token:
                raise OpsApiError("Not authenticated - call login() first")
            headers["Authorization"] = f"OpsToken {self._token}"

        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_context) as resp:
                LOG.debug(f"{method} {path} -> HTTP {resp.status}")
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            LOG.error(f"{method} {path} -> HTTP {e.code}: {body}")
            raise OpsApiError(f"{method} {path} -> HTTP {e.code}: {body}") from None
        except urllib.error.URLError as e:
            LOG.error(f"{method} {path} -> connection error: {e.reason}")
            raise OpsApiError(f"{method} {path} -> connection error: {e.reason}") from None

    def login(self) -> None:
        data = self._request(
            "POST", "/api/auth/token/acquire",
            json_body={"username": self.username, "password": self.password},
            authed=False,
        )
        token = data.get("token")
        if not token:
            raise OpsApiError("Login succeeded but no token was returned")
        self._token = token
        LOG.info(f"Authenticated as {self.username} (token acquired, not logged)")

    def get_master_details(self, vcf_instance_id: str) -> dict:
        """GET /api/salt/master?resourceId=<id> -> {resourceId, masterId, masterFqdn,
        masterPublicKey (base64 of the PEM text), masterKeyState, presenceStatus}."""
        return self._request("GET", "/api/salt/master", params={"resourceId": vcf_instance_id})

    def add_trusted_key(self, minion_id: str, master_id: str, minion_public_key_pem: str) -> dict:
        """POST /api/salt/minions/{minionId}/trusted-keys
        Body: {masterId, minionPublicKey} - minionPublicKey is RAW PEM text here
        (NOT base64-encoded - only the master pubkey in GET responses is)."""
        return self._request(
            "POST", f"/api/salt/minions/{minion_id}/trusted-keys",
            json_body={"masterId": master_id, "minionPublicKey": minion_public_key_pem},
        )


# --------------------------------------------------------------------------
# Salt master_finger computation
# --------------------------------------------------------------------------

def pem_finger(pem_text: str, sum_type: str = "sha256") -> str:
    """
    Reproduces Salt's own salt.utils.crypt.pem_finger(): strip the PEM
    header/footer lines, base64-decode the body to raw DER bytes, hash them,
    and format as colon-separated hex pairs - the exact string Salt expects
    for `master_finger` / SALT_MASTER_FINGER.
    """
    lines = [l for l in pem_text.strip().splitlines() if l.strip()]
    if len(lines) < 3:
        raise ValueError("Master public key does not look like a PEM block")
    body = "".join(lines[1:-1])
    der = base64.b64decode(body)
    digest = hashlib.new(sum_type, der).hexdigest()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


# --------------------------------------------------------------------------
# Docker deployment
# --------------------------------------------------------------------------

@dataclass
class DockerConfig:
    image: str
    container_name: str
    volume: str
    master_fqdn: str
    master_finger: str
    minion_id: str


def docker_container_exists(name: str, dry_run: bool) -> bool:
    if dry_run:
        return False
    out = run(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
              capture=True, check=False)
    return out.strip() == name


def docker_start(cfg: DockerConfig, dry_run: bool, assume_yes: bool = False) -> None:
    if docker_container_exists(cfg.container_name, dry_run):
        warn(f"A container named '{cfg.container_name}' already exists "
             f"(likely left over from a previous attempt).")
        if confirm(f"Remove it and continue?", default=True, assume_yes=assume_yes):
            run(["docker", "rm", "-f", cfg.container_name], dry_run=dry_run)
        else:
            die(f"Container '{cfg.container_name}' already exists. "
                f"Choose a different --container-name or remove it manually with "
                f"`docker rm -f {cfg.container_name}`.")

    cmd = [
        "docker", "run", "-d",
        "--name", cfg.container_name,
        "-e", f"SALT_MASTER={cfg.master_fqdn}",
        "-e", f"SALT_MASTER_FINGER={cfg.master_finger}",
        "-e", f"SALT_MINION_ID={cfg.minion_id}",
        "-v", f"{cfg.volume}:/etc/salt/pki/minion",
        cfg.image,
    ]
    run(cmd, dry_run=dry_run)


def docker_exec(container: str, args: list, dry_run: bool = False, check: bool = True) -> str:
    return run(["docker", "exec", container] + args, dry_run=dry_run, capture=True, check=check)


def docker_read_minion_pubkey(container: str, timeout: int, dry_run: bool) -> str:
    if dry_run:
        return "-----BEGIN PUBLIC KEY-----\nAAAAAAAAAAAAAAAAAAAAAAAA\n-----END PUBLIC KEY-----"

    result = {}

    def _check() -> bool:
        pubkey = docker_exec(container, ["cat", "/etc/salt/pki/minion/minion.pub"], check=False)
        if pubkey.startswith("-----BEGIN PUBLIC KEY-----"):
            result["pubkey"] = pubkey
            return True
        return False

    if not wait_until(_check, timeout=timeout, check_interval=2,
                       message="Waiting for minion to generate its keypair", dry_run=dry_run):
        die(f"Timed out waiting for {container} to generate its minion keypair. "
            f"Check `docker logs {container}`.")
    return result["pubkey"]


MINION_READY_LOG_MARKER = "Minion is ready to receive requests"


def docker_is_connected(container: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    # status.master's answer depends on master_alive_interval being configured on the
    # minion, which this image's entrypoint does not set - it can under-report even
    # once actually connected. The log line below is emitted once, event-driven, the
    # moment the pub/req channels with the master are established, so it doesn't have
    # that gap; treat either signal as sufficient.
    out = docker_exec(
        container,
        ["salt-call", "--out=newline_values_only", "--retcode-passthrough", "status.master"],
        check=False,
    )
    if out.strip().lower() == "true":
        return True
    logs = run(["docker", "logs", container], dry_run=dry_run, capture=True, check=False)
    return MINION_READY_LOG_MARKER in logs


# --------------------------------------------------------------------------
# Kubernetes / Helm deployment
# --------------------------------------------------------------------------

@dataclass
class HelmConfig:
    chart_path: str
    release_name: str
    namespace: str
    image_repository: str
    image_tag: str
    master_fqdn: str
    master_finger: str
    minion_id: str


def helm_start(cfg: HelmConfig, dry_run: bool) -> None:
    cmd = [
        "helm", "upgrade", "--install", cfg.release_name, cfg.chart_path,
        "--namespace", cfg.namespace, "--create-namespace",
        "--set", f"salt.master={cfg.master_fqdn}",
        "--set", f"salt.masterFinger={cfg.master_finger}",
        "--set", f"salt.minionId={cfg.minion_id}",
        "--set", f"image.repository={cfg.image_repository}",
        "--set", f"image.tag={cfg.image_tag}",
    ]
    run(cmd, dry_run=dry_run)


def kubectl_get_pod_name(namespace: str, release_name: str, dry_run: bool, timeout: int = 60) -> str:
    if dry_run:
        return f"{release_name}-salt-minion-vcf-0"

    selector = f"app.kubernetes.io/name=salt-minion-vcf,app.kubernetes.io/instance={release_name}"
    result = {}

    def _check() -> bool:
        name = run(
            ["kubectl", "get", "pods", "-n", namespace, "-l", selector,
             "-o", "jsonpath={.items[0].metadata.name}"],
            capture=True, check=False,
        )
        if name:
            result["name"] = name
            return True
        return False

    if not wait_until(_check, timeout=timeout, check_interval=2,
                       message="Waiting for the Pod to be scheduled", dry_run=dry_run):
        die(f"Timed out waiting for a Pod matching '{selector}' in namespace {namespace}.")
    return result["name"]


def kubectl_exec(namespace: str, pod: str, args: list, dry_run: bool = False, check: bool = True) -> str:
    return run(["kubectl", "exec", "-n", namespace, pod, "--"] + args,
               dry_run=dry_run, capture=True, check=check)


def kubectl_read_minion_pubkey(namespace: str, pod: str, timeout: int, dry_run: bool) -> str:
    if dry_run:
        return "-----BEGIN PUBLIC KEY-----\nAAAAAAAAAAAAAAAAAAAAAAAA\n-----END PUBLIC KEY-----"

    result = {}

    def _check() -> bool:
        pubkey = kubectl_exec(namespace, pod, ["cat", "/etc/salt/pki/minion/minion.pub"], check=False)
        if pubkey.startswith("-----BEGIN PUBLIC KEY-----"):
            result["pubkey"] = pubkey
            return True
        return False

    if not wait_until(_check, timeout=timeout, check_interval=2,
                       message="Waiting for minion to generate its keypair", dry_run=dry_run):
        die(f"Timed out waiting for {pod} to generate its minion keypair. "
            f"Check `kubectl logs -n {namespace} {pod}`.")
    return result["pubkey"]


def kubectl_is_connected(namespace: str, pod: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    # See the comment on docker_is_connected() - status.master alone can under-report;
    # the log marker is an event-driven signal emitted only after successful auth.
    out = kubectl_exec(
        namespace, pod,
        ["salt-call", "--out=newline_values_only", "--retcode-passthrough", "status.master"],
        check=False,
    )
    if out.strip().lower() == "true":
        return True
    logs = run(["kubectl", "logs", "-n", namespace, pod], dry_run=dry_run, capture=True, check=False)
    return MINION_READY_LOG_MARKER in logs


# --------------------------------------------------------------------------
# Main orchestration
# --------------------------------------------------------------------------

TOTAL_STEPS = 7


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Onboard a salt-minion-vcf instance against a VCF Operations-managed Salt master.",
    )
    p.add_argument("--ops-host", help="VCF Operations FQDN or IP")
    p.add_argument("--ops-user", help="VCF Operations username")
    p.add_argument("--ops-base-path", default="/suite-api",
                   help="Suite API base path (default: /suite-api)")
    p.add_argument("--insecure", action="store_true",
                   help="Skip TLS certificate verification against VCF Operations")
    p.add_argument("--vcf-instance-id", help="VCF instance resource UUID whose master to use")

    p.add_argument("--deployment", choices=["docker", "kubernetes"],
                   help="Where to run the minion")

    p.add_argument("--minion-id", help="Explicit minion ID (default: auto-generated)")
    p.add_argument("--minion-id-prefix", default="ext-minion",
                   help="Prefix for the auto-generated minion ID (default: ext-minion)")

    # Docker options. Defaults are intentionally None (not the literal
    # default value) so the script can tell "explicitly passed on the CLI"
    # apart from "use the built-in default" - only the first minion in a
    # session honors these directly; see onboard_one_minion().
    p.add_argument("--image", help="[docker] image:tag to run (default: salt-minion-vcf:0.1.0)")
    p.add_argument("--container-name", help="[docker] container name (default: salt-minion-vcf)")
    p.add_argument("--volume", help="[docker] PKI volume name (default: salt-minion-vcf-pki)")

    # Kubernetes/Helm options
    p.add_argument("--chart-path", default="./helm/salt-minion-vcf", help="[k8s] path to the Helm chart")
    p.add_argument("--release-name", help="[k8s] Helm release name (default: vcf-executor)")
    p.add_argument("--namespace", help="[k8s] target namespace (default: vcf-salt)")
    p.add_argument("--image-repository", help="[k8s] image repository (default: salt-minion-vcf)")
    p.add_argument("--image-tag", help="[k8s] image tag (default: 0.1.0)")

    p.add_argument("--master-finger-algo", default="sha256", choices=["sha256", "md5"],
                   help="Hash algorithm for master_finger (default: sha256, matches modern Salt)")
    p.add_argument("--connect-timeout", type=int, default=300,
                   help="Seconds to wait for the minion to connect (default: 300)")
    p.add_argument("--poll-interval", type=int, default=5,
                   help="Seconds between connection status checks (default: 5)")
    p.add_argument("-y", "--yes", action="store_true", help="Assume yes on all confirmations")
    p.add_argument("--dry-run", action="store_true",
                   help="Print every command/API call without executing anything")
    p.add_argument("--log-file", help="Path to the audit log file "
                                       "(default: vcf-ops-onboard-<timestamp>.log)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Also print detailed debug logging to the console")
    return p


DEFAULT_IMAGE = "salt-minion-vcf:0.1.0"
DEFAULT_CONTAINER_NAME = "salt-minion-vcf"
DEFAULT_VOLUME = "salt-minion-vcf-pki"
DEFAULT_RELEASE_NAME = "vcf-executor"
DEFAULT_NAMESPACE = "vcf-salt"
DEFAULT_IMAGE_REPOSITORY = "salt-minion-vcf"
DEFAULT_IMAGE_TAG = "0.1.0"


def onboard_one_minion(client: OpsClient, args: argparse.Namespace,
                        master_id: str, master_fqdn: str, master_finger: str,
                        deployment: str, defaults: dict, index: int) -> dict:
    """
    Runs steps 4-7 for a single minion and returns a summary dict.

    `index` counts minions onboarded in this session (starting at 1). CLI
    flags for identity-bearing settings (minion ID, container/volume/release
    name) are only honored on the first minion - a container name, PKI
    volume, or Helm release can't be reused for a second minion without
    colliding, so from the second minion onward this always prompts, with an
    auto-suffixed suggestion ("-2", "-3", ...) to avoid that collision.
    """

    # ---------------------------------------------------------------- Step 4
    step(4, TOTAL_STEPS, "Start the minion")
    suffix = "" if index == 1 else f"-{index}"

    minion_id = (args.minion_id if index == 1 else None) or prompt(
        "Minion ID", default=f"{args.minion_id_prefix}-{uuid.uuid4()}")

    if deployment == "docker":
        container_name = (args.container_name if index == 1 else None) or prompt(
            "Container name", default=f"{DEFAULT_CONTAINER_NAME}{suffix}")
        image = args.image or defaults.get("image") or prompt("Image", default=DEFAULT_IMAGE)
        volume = (args.volume if index == 1 else None) or prompt(
            "PKI volume name", default=f"{DEFAULT_VOLUME}{suffix}")
        if volume.startswith("/"):
            warn(f"'{volume}' looks like a host path, not a named Docker volume - "
                 f"it will be bind-mounted as-is. The container runs as non-root uid 10000, "
                 f"so that host directory must already exist and be writable by uid 10000 "
                 f"(e.g. `mkdir -p {volume} && chown 10000:10000 {volume}`), or the minion "
                 f"will fail to write its keys there.")

        print_summary("Review before starting the minion", [
            ("Deployment", "docker"),
            ("Minion ID", minion_id),
            ("Image", image),
            ("Container name", container_name),
            ("PKI volume", volume),
            ("Salt master", f"{master_fqdn} (master_finger computed)"),
        ])
        if not confirm("Proceed with these settings?", assume_yes=args.yes):
            die("Aborted by user.", code=0)

        docker_cfg = DockerConfig(
            image=image, container_name=container_name, volume=volume,
            master_fqdn=master_fqdn, master_finger=master_finger, minion_id=minion_id,
        )
        docker_start(docker_cfg, dry_run=args.dry_run, assume_yes=args.yes)
        ok(f"Container '{container_name}' started")
        defaults["image"] = image
        pod_name = None
    else:
        release_name = (args.release_name if index == 1 else None) or prompt(
            "Helm release name", default=f"{DEFAULT_RELEASE_NAME}{suffix}")
        namespace = args.namespace or defaults.get("namespace") or prompt(
            "Namespace", default=DEFAULT_NAMESPACE)
        image_repository = args.image_repository or defaults.get("image_repository") or prompt(
            "Image repository", default=DEFAULT_IMAGE_REPOSITORY)
        image_tag = args.image_tag or defaults.get("image_tag") or prompt(
            "Image tag", default=DEFAULT_IMAGE_TAG)

        print_summary("Review before starting the minion", [
            ("Deployment", "kubernetes"),
            ("Minion ID", minion_id),
            ("Release name", release_name),
            ("Namespace", namespace),
            ("Image", f"{image_repository}:{image_tag}"),
            ("Salt master", f"{master_fqdn} (master_finger computed)"),
        ])
        if not confirm("Proceed with these settings?", assume_yes=args.yes):
            die("Aborted by user.", code=0)

        helm_cfg = HelmConfig(
            chart_path=args.chart_path, release_name=release_name, namespace=namespace,
            image_repository=image_repository, image_tag=image_tag,
            master_fqdn=master_fqdn, master_finger=master_finger, minion_id=minion_id,
        )
        helm_start(helm_cfg, dry_run=args.dry_run)
        ok(f"Helm release '{release_name}' installed/upgraded in namespace {namespace}")
        defaults["namespace"] = namespace
        defaults["image_repository"] = image_repository
        defaults["image_tag"] = image_tag
        pod_name = kubectl_get_pod_name(namespace, release_name, dry_run=args.dry_run)
        ok(f"Pod: {pod_name}")

    # ---------------------------------------------------------------- Step 5
    step(5, TOTAL_STEPS, "Read the minion's public key")
    if deployment == "docker":
        minion_pubkey_pem = docker_read_minion_pubkey(container_name, timeout=60, dry_run=args.dry_run)
    else:
        minion_pubkey_pem = kubectl_read_minion_pubkey(namespace, pod_name, timeout=60, dry_run=args.dry_run)
    ok("Minion public key retrieved (private key never left the minion)")

    # ---------------------------------------------------------------- Step 6
    step(6, TOTAL_STEPS, "Trust the minion's key against the master")
    if not confirm(f"Register minion '{minion_id}' as trusted against master '{master_id}'?",
                   assume_yes=args.yes):
        die("Aborted by user.", code=0)
    if args.dry_run:
        info(f"(dry-run) POST /api/salt/minions/{minion_id}/trusted-keys "
             f"{{masterId: {master_id}, minionPublicKey: <PEM>}}")
    else:
        try:
            trust_result = client.add_trusted_key(minion_id, master_id, minion_pubkey_pem)
        except OpsApiError as e:
            die(f"Failed to register the trusted key: {e}")
        if trust_result.get("status", "").upper() not in ("SUCCESS", ""):
            die(f"Trust registration reported failure: {trust_result}")
    ok("Minion key trusted with the Salt master")

    # ---------------------------------------------------------------- Step 7
    step(7, TOTAL_STEPS, "Wait for the minion to connect")

    def _connected() -> bool:
        if deployment == "docker":
            return docker_is_connected(container_name, dry_run=args.dry_run)
        return kubectl_is_connected(namespace, pod_name, dry_run=args.dry_run)

    connected = wait_until(_connected, timeout=args.connect_timeout,
                            check_interval=args.poll_interval,
                            message="Waiting for the master to accept the minion", dry_run=args.dry_run)
    if not connected:
        die(f"Minion did not connect within {args.connect_timeout}s. "
            f"Check the master's `salt-key -L` and the minion's logs.")
    ok("Minion connected to the Salt master")

    return {"minion_id": minion_id, "deployment": deployment}


def main() -> None:
    args = build_arg_parser().parse_args()
    log_file = args.log_file or f"vcf-ops-onboard-{datetime.now():%Y%m%d-%H%M%S}.log"
    setup_logging(log_file, verbose=args.verbose)
    LOG.info(f"vcf-ops-onboard started, args={vars(args)}")

    print(f"{_C.BOLD}VCF Operations - External Minion Onboarding{_C.RESET}")
    info(f"Logging full step-by-step detail to: {log_file}")
    if args.dry_run:
        warn("Running in --dry-run mode: nothing will actually be executed.")

    # ---------------------------------------------------------------- Step 1
    step(1, TOTAL_STEPS, "Connect to VCF Operations")
    ops_host = args.ops_host or prompt("VCF Operations FQDN or IP")
    ops_user = args.ops_user or prompt("Username")
    ops_password = prompt("Password", secret=True)
    verify_tls = not args.insecure
    if not verify_tls:
        warn("TLS certificate verification is disabled for this session.")

    client = OpsClient(ops_host, ops_user, ops_password,
                        base_path=args.ops_base_path, verify_tls=verify_tls)
    if not args.dry_run:
        try:
            client.login()
        except OpsApiError as e:
            die(f"Login failed: {e}")
    ok(f"Authenticated to {ops_host}")

    # ---------------------------------------------------------------- Step 2
    step(2, TOTAL_STEPS, "Resolve the Salt master for your VCF instance")
    vcf_instance_id = args.vcf_instance_id or prompt_uuid("VCF instance resource ID (UUID)")

    if args.dry_run:
        master = {"masterId": "salt-master-<dry-run>", "masterFqdn": "salt-master.example.com",
                  "masterPublicKey": base64.b64encode(
                      b"-----BEGIN PUBLIC KEY-----\nAAAAAAAAAAAAAAAAAAAAAAAA\n-----END PUBLIC KEY-----").decode()}
    else:
        try:
            master = client.get_master_details(vcf_instance_id)
        except OpsApiError as e:
            die(f"Could not resolve master details: {e}")

    master_id = master["masterId"]
    master_fqdn = master["masterFqdn"]
    master_pubkey_pem = base64.b64decode(master["masterPublicKey"]).decode("utf-8")
    ok(f"Master resolved: {master_id} @ {master_fqdn}")

    # ---------------------------------------------------------------- Step 3
    step(3, TOTAL_STEPS, "Compute master identity fingerprint")
    master_finger = pem_finger(master_pubkey_pem, sum_type=args.master_finger_algo)
    ok(f"master_finger ({args.master_finger_algo}): {master_finger}")

    # ------------------------------------------------- Steps 4-7 (repeatable)
    deployment = args.deployment or choose(
        "\nWhere should this minion run?", ["docker", "kubernetes"], default="docker")

    onboarded = []
    defaults: dict = {}
    index = 1
    while True:
        result = onboard_one_minion(client, args, master_id, master_fqdn, master_finger,
                                     deployment, defaults, index)
        onboarded.append(result)

        print(f"\n{_C.BOLD}{_C.GREEN}Minion onboarded{_C.RESET}")
        print(f"  Minion ID : {result['minion_id']}")
        print(f"  Master    : {master_id} @ {master_fqdn}")
        print(f"  Deployment: {result['deployment']}")
        print(f"\nVerify from the Salt master:\n  salt '{result['minion_id']}' test.ping")

        if args.dry_run or not confirm(
                "\nOnboard another minion against this same master?", default=False, assume_yes=False):
            break
        index += 1

    print(f"\n{_C.BOLD}Session summary{_C.RESET} ({len(onboarded)} minion(s) onboarded)")
    for r in onboarded:
        print(f"  - {r['minion_id']} ({r['deployment']})")
    print(f"\nFull audit log: {log_file}")
    LOG.info(f"Session complete: {len(onboarded)} minion(s) onboarded: "
             f"{[r['minion_id'] for r in onboarded]}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        die("Interrupted by user.", code=130)
