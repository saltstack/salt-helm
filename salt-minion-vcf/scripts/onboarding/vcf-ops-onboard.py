#!/usr/bin/env python3
"""
vcf-ops-onboard.py

Interactive tool for managing externally managed Salt minions against a VCF
Operations-managed Salt master. Supports three actions (--action, or picked
interactively):

  configure - registers a NEW minion's key as trusted, then brings up a
              salt-minion-vcf instance (Docker or Kubernetes/Helm) that is
              already trusted on first connect.
      1. Prompt for VCF Operations (Suite API) connection details and log in.
      2. List every Salt master known to VCF Operations
         (GET /api/salt/masters) and interactively select one - by FQDN, with
         its key/presence state shown so you don't pick a master that isn't
         actually usable.
      3. Generate a fresh RSA keypair for the minion, locally, via `openssl`.
         The private key never leaves this process except to be handed
         directly to the minion's own runtime (an env var for Docker, or a
         Kubernetes Secret this script creates for you) - it is never sent to
         VCF Operations, and never written to the console or the audit log.
      4. Register the minion's public key as trusted against the selected
         master (POST /api/salt/minions). The minion ID is always assigned by
         VCF Operations, not chosen here - the response is the first time this
         script (or you) learns what it is.
      5. Start the minion (docker run, or helm install/upgrade), pre-seeded
         with that exact keypair and minion ID, and with the master's actual
         public key (not just its fingerprint) so it trusts the master
         directly on first connect - the same approach VCF's own internal
         component minions use. Because the trust relationship was already
         established in step 4 *before* the minion ever starts, there is no
         manual `salt-key -a` step and no waiting-for-acceptance window.
      6. Poll the minion (already retrying in the background) until it
         connects, primarily by watching its logs for the event-driven "Minion
         is ready to receive requests" line, falling back to a time-boxed
         `salt-call status.master` (the same check the image's own healthcheck/
         readiness probe uses, but that check alone can hang or under-report -
         see the comments on docker_is_connected()/kubectl_is_connected()).
      Steps 3-6 can be repeated for multiple minions in one session without
      re-entering VCF Operations credentials or re-listing masters.

  rotate    - rotates the key of an ALREADY-onboarded minion. The minion is
              identified by its CURRENT public key (read straight off the
              running container/pod's PKI dir), not by minion ID - the rotate
              API (POST /api/salt/minions/rotate) never accepts minion ID as
              input either. A fresh keypair is generated, registered via the
              rotate API (which re-registers the SAME minion record, RaaS-side,
              with the new key), and the running instance is then given the
              new keypair and restarted: the container is recreated for
              Docker (env vars are fixed at container creation, so this is
              the only way to feed it a new keypair), or the Pod's key Secret
              is updated and the Pod is deleted/recreated for Kubernetes.

  list      - a read-only listing of trusted minions (GET /api/salt/minions),
              including each minion's live presence status and resourceKind
              (its vcfops_resource_kind grain, if it has reported one) - handy
              for finding a minion's master/state before rotating its key.

Every step is written to a timestamped log file (default:
vcf-ops-onboard-<timestamp>.log) in addition to the interactive console
output, for audit/troubleshooting. Passwords, auth tokens, and private key
material are never logged.

Only three dependencies: Python 3.8+, `openssl` (minion keypair generation),
and whichever of `docker`/`helm`+`kubectl` you're deploying with. No
third-party pip packages required.

Reference: https://github.com/saltstack/salt-helm/tree/main/salt-minion-vcf
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import logging
import shlex
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional


LOG = logging.getLogger("vcf_onboard")

HEALTHY_KEY_STATE = "ACCEPTED"
HEALTHY_PRESENCE = "PRESENT"


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

def run(cmd: list, dry_run: bool = False, capture: bool = False, check: bool = True,
        timeout: float = None, input_data: Optional[str] = None,
        redact_input_in_log: bool = False) -> str:
    printable = " ".join(shlex.quote(c) for c in cmd)
    stdin_note = " < <redacted>" if (input_data and redact_input_in_log) else (" < -" if input_data else "")
    print(f"  $ {printable}{stdin_note}")
    LOG.debug(f"$ {printable}{stdin_note}")
    if dry_run:
        return ""
    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            check=check,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        die(f"Command not found: {cmd[0]}. Is it installed and on PATH?")
    except subprocess.TimeoutExpired:
        LOG.warning(f"command timed out after {timeout}s: {printable}")
        if check:
            raise
        return ""
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
    Thin client for the two VCF Operations Salt trust-management endpoints
    this script needs: listing masters, and registering a minion's key.

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

    def list_masters(self, page_size: int = 1000) -> list:
        """GET /api/salt/masters -> a page of
        {masterId, masterFqdn, masterPublicKey (base64), masterKeyState,
        presenceStatus}. Unscoped - no VCF instance/resource ID needed.

        Fetches a single large page, which is fine for interactive use;
        if your environment has more masters than page_size, pass a larger
        value or add real pagination here."""
        result = self._request("GET", "/api/salt/masters", params={"page": 0, "pageSize": page_size})
        masters = result.get("masters", [])
        page_info = result.get("pageInfo") or {}
        total = page_info.get("totalCount")
        if isinstance(total, int) and total > len(masters):
            warn(f"VCF Operations reports {total} master(s) total, but only {len(masters)} were "
                 f"fetched (page_size={page_size}). Increase --master-page-size to see the rest.")
        LOG.debug(f"GET /api/salt/masters response body: {result}")
        return masters

    def create_minion(self, master_id: str, minion_public_key_pem: str) -> dict:
        """POST /api/salt/minions
        Body: {masterId, minionPublicKey}. The minion ID is always assigned
        by VCF Operations - it is not accepted as request input. Response:
        {minionId, masterId, minionPublicKey, masterPublicKey (base64),
        masterFqdn, keyState}."""
        result = self._request(
            "POST", "/api/salt/minions",
            json_body={"masterId": master_id, "minionPublicKey": minion_public_key_pem},
        )
        LOG.debug(f"POST /api/salt/minions response body: {result}")
        return result

    def rotate_minion_key(self, master_id: str, current_minion_public_key_pem: str,
                           new_minion_public_key_pem: str) -> dict:
        """POST /api/salt/minions/rotate
        Body: {masterId, currentMinionPublicKey, newMinionPublicKey}. The
        minion to rotate is never identified by minionId - it is resolved
        server-side from currentMinionPublicKey instead, then re-registered
        with newMinionPublicKey. Response: {minionId, masterId,
        minionPublicKey, masterPublicKey (base64), masterFqdn, keyState} -
        the same shape as create_minion()'s response."""
        result = self._request(
            "POST", "/api/salt/minions/rotate",
            json_body={
                "masterId": master_id,
                "currentMinionPublicKey": current_minion_public_key_pem,
                "newMinionPublicKey": new_minion_public_key_pem,
            },
        )
        LOG.debug(f"POST /api/salt/minions/rotate response body: {result}")
        return result

    def list_minions(self, state: Optional[str] = None, page_size: int = 1000) -> list:
        """GET /api/salt/minions -> a page of
        {minionId, masterId, minionPublicKey, keyState, presenceStatus,
        resourceKind, description, createdAt, updatedAt, acceptedAt,
        rejectedAt}. resourceKind is the minion's vcfops_resource_kind grain
        (e.g. "vcenter", "sddcm") - null until the minion's own bootstrap
        sets it and it syncs to the master."""
        params = {"page": 0, "pageSize": page_size}
        if state:
            params["state"] = state
        result = self._request("GET", "/api/salt/minions", params=params)
        minions = result.get("minions", [])
        page_info = result.get("pageInfo") or {}
        total = page_info.get("totalCount")
        if isinstance(total, int) and total > len(minions):
            warn(f"VCF Operations reports {total} minion(s) total, but only {len(minions)} were "
                 f"fetched (page_size={page_size}). Increase --minion-page-size to see the rest.")
        LOG.debug(f"GET /api/salt/minions response body: {result}")
        return minions


# --------------------------------------------------------------------------
# Master selection
# --------------------------------------------------------------------------

def _is_healthy_master(master: dict) -> bool:
    return (master.get("masterKeyState") or "").upper() == HEALTHY_KEY_STATE \
        and (master.get("presenceStatus") or "").upper() == HEALTHY_PRESENCE


def select_master(client: OpsClient, args: argparse.Namespace) -> dict:
    """Lists every Salt master known to VCF Operations and either honors
    --master-id (still validated against the live list) or prompts the user
    to choose one interactively, by FQDN, with key/presence state shown so
    an unusable master isn't picked by accident."""
    if args.dry_run:
        masters = [{
            "masterId": "salt-master-<dry-run>",
            "masterFqdn": "salt-master.example.com",
            "masterKeyState": HEALTHY_KEY_STATE,
            "presenceStatus": HEALTHY_PRESENCE,
            "masterPublicKey": base64.b64encode(
                b"-----BEGIN PUBLIC KEY-----\nAAAAAAAAAAAAAAAAAAAAAAAA\n-----END PUBLIC KEY-----").decode(),
        }]
    else:
        try:
            masters = client.list_masters(page_size=args.master_page_size)
        except OpsApiError as e:
            die(f"Could not list Salt masters: {e}")

    if not masters:
        die("No Salt masters are known to VCF Operations. Nothing to onboard against.")

    print(f"\n{_C.BOLD}Available Salt masters{_C.RESET}")
    print(f"{_C.DIM}{'-' * 92}{_C.RESET}")
    print(f"  {'#':<3} {'FQDN':<38} {'Master ID':<28} {'Key State':<10} Presence")
    for i, m in enumerate(masters, 1):
        healthy = _is_healthy_master(m)
        flag = "" if healthy else f"  {_C.YELLOW}<- not {HEALTHY_KEY_STATE}/{HEALTHY_PRESENCE}{_C.RESET}"
        print(f"  {i:<3} {str(m.get('masterFqdn', '')):<38} {str(m.get('masterId', '')):<28} "
              f"{str(m.get('masterKeyState', '')):<10} {str(m.get('presenceStatus', ''))}{flag}")
    print(f"{_C.DIM}{'-' * 92}{_C.RESET}")

    unhealthy_count = sum(1 for m in masters if not _is_healthy_master(m))
    if unhealthy_count:
        warn(f"{unhealthy_count} master(s) above are not {HEALTHY_KEY_STATE}/{HEALTHY_PRESENCE} - "
             f"onboarding against one of them will likely fail, or leave the minion unable to "
             f"connect even after trust is registered.")

    chosen = None
    if args.master_id:
        chosen = next((m for m in masters if m.get("masterId") == args.master_id), None)
        if chosen is None:
            die(f"--master-id '{args.master_id}' was not found in the list above.")
        LOG.debug(f"--master-id matched: {chosen}")
    else:
        while True:
            raw = prompt("Select a master by number")
            if raw.isdigit() and 1 <= int(raw) <= len(masters):
                chosen = masters[int(raw) - 1]
                break
            print(f"  Please enter a number between 1 and {len(masters)}")

    if not _is_healthy_master(chosen):
        if not confirm(
                f"'{chosen.get('masterFqdn')}' is not {HEALTHY_KEY_STATE}/{HEALTHY_PRESENCE} "
                f"(state={chosen.get('masterKeyState')}, presence={chosen.get('presenceStatus')}). "
                f"Proceed anyway?", default=False, assume_yes=args.yes):
            die("Aborted by user.", code=0)

    ok(f"Selected master: {chosen.get('masterId')} @ {chosen.get('masterFqdn')}")
    return chosen


# --------------------------------------------------------------------------
# Minion RSA keypair generation
# --------------------------------------------------------------------------

def generate_minion_keypair(key_size: int, dry_run: bool) -> "tuple[str, str]":
    """
    Generates a fresh RSA keypair for the minion via `openssl` - the only
    external tool this needs beyond docker/helm/kubectl, so no third-party
    pip dependency is required. Returns (private_key_pem, public_key_pem).

    The private key is generated here, in this process, and handed directly
    to the minion's own runtime (an env var for Docker, a Kubernetes Secret
    this script creates for you) - it is never sent to VCF Operations, and
    never written to the console or the audit log.
    """
    LOG.info(f"$ openssl genrsa {key_size}  (output not logged: private key material)")
    if dry_run:
        return (
            "-----BEGIN PRIVATE KEY-----\n<dry-run - no key generated>\n-----END PRIVATE KEY-----\n",
            "-----BEGIN PUBLIC KEY-----\n<dry-run - no key generated>\n-----END PUBLIC KEY-----\n",
        )
    try:
        priv = subprocess.run(
            ["openssl", "genrsa", str(key_size)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout
    except FileNotFoundError:
        die("Command not found: openssl. Install it and ensure it's on PATH.")
        raise  # unreachable, keeps type-checkers happy
    except subprocess.CalledProcessError as e:
        die(f"Failed to generate the minion's RSA keypair: {e.stderr.strip()}")
        raise  # unreachable

    LOG.debug("$ openssl rsa -pubout")
    try:
        pub = subprocess.run(
            ["openssl", "rsa", "-pubout"],
            input=priv, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        die(f"Failed to derive the minion's public key: {e.stderr.strip()}")
        raise  # unreachable

    return priv, pub


# --------------------------------------------------------------------------
# Docker deployment
# --------------------------------------------------------------------------

@dataclass
class DockerConfig:
    image: str
    container_name: str
    volume: str
    master_fqdn: str
    master_pubkey_b64: str
    minion_id: str
    minion_private_key_b64: str
    minion_public_key_b64: str


def docker_container_exists(name: str, dry_run: bool) -> bool:
    if dry_run:
        return False
    out = run(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
              capture=True, check=False)
    return out.strip() == name


def resolve_master_fqdn_on_host(master_fqdn: str) -> Optional[str]:
    """
    Resolves master_fqdn the same way this host's own resolver would (which
    covers a static /etc/hosts entry, not just real DNS) - internal-only
    hostnames (e.g. "*.vrack.vsphere.internal" in on-prem/lab environments)
    are very often only resolvable via such a static entry on the host, and
    Docker containers do NOT inherit the host's /etc/hosts automatically.
    Returns None (rather than raising) if the host itself can't resolve it
    either - in that case the container is no worse off than before, and
    presumably relies on the same DNS Docker's embedded resolver forwards to.
    """
    try:
        return socket.gethostbyname(master_fqdn)
    except OSError:
        return None


def docker_clear_pki_volume(volume: str, image: str, dry_run: bool) -> None:
    """
    Ensures the named PKI volume has no leftover minion.pem/minion.pub from a
    PREVIOUS container before this one writes a freshly generated keypair
    into it.
    <p>
    A named Docker volume outlives `docker rm` - it is not tied to any one
    container's lifecycle. docker-entrypoint.sh only pre-seeds the keypair
    from SALT_MINION_PRIVATE_KEY_B64/PUBLIC_KEY_B64 when minion.pem doesn't
    already exist (so a genuine restart of the SAME identity correctly keeps
    it) - but that means reusing a volume name across separate
    configure/rotate runs would otherwise silently keep the OLD identity's
    key files, and the container would run on a key that was never the one
    just registered via createMinion/rotateMinionKey. This can go
    unnoticed: a never-before-seen minion ID still gets auto-accepted by the
    real Salt master regardless of which key it presents (auto_accept
    doesn't cross-check against RaaS's trust store for a fresh ID), so the
    mismatch doesn't surface as a rejection - only as a minion whose actual
    key silently doesn't match what VCF Operations thinks is trusted for it.
    <p>
    Both configure and rotate always have a genuinely fresh keypair to write
    at this point, so clearing first is always correct here - never confirm,
    never destructive to anything the user intended to keep.
    <p>
    Runs as root (-u root): the image's default container user is a non-root
    uid, and --volume can also be a bind-mounted host path (e.g. /root/keys)
    rather than a Docker-managed named volume - such a path is very commonly
    root-owned on the host, and the non-root default user would silently
    fail (permission denied) to delete anything there, leaving the stale
    files in place with no visible error.
    """
    run(["docker", "run", "--rm", "-u", "root", "-v", f"{volume}:/etc/salt/pki/minion", image,
         "rm", "-f", PKI_MINION_PEM, PKI_MINION_PUB], dry_run=dry_run, check=False)


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

    docker_clear_pki_volume(cfg.volume, cfg.image, dry_run)

    cmd = [
        "docker", "run", "-d",
        "--name", cfg.container_name,
    ]

    # Give the container the SAME resolution for the master's FQDN that this
    # host already has - whether that's real DNS or (very commonly, for
    # internal-only hostnames) just a static /etc/hosts entry that Docker's
    # container would otherwise have no way to see. Generic: works for any
    # master FQDN, on any host, without the user needing to look up or supply
    # an IP themselves. --add-host only takes effect at container creation,
    # which is fine here since both configure and rotate always (re)create
    # the container.
    resolved_master_ip = resolve_master_fqdn_on_host(cfg.master_fqdn) if not dry_run else None
    if resolved_master_ip:
        info(f"Resolved master FQDN '{cfg.master_fqdn}' to {resolved_master_ip} on this host - "
             f"passing --add-host so the container can resolve it too.")
        cmd += ["--add-host", f"{cfg.master_fqdn}:{resolved_master_ip}"]

    cmd += [
        "-e", f"SALT_MASTER={cfg.master_fqdn}",
        "-e", f"SALT_MASTER_PUBKEY_B64={cfg.master_pubkey_b64}",
        "-e", f"SALT_MINION_ID={cfg.minion_id}",
        "-e", f"SALT_MINION_PRIVATE_KEY_B64={cfg.minion_private_key_b64}",
        "-e", f"SALT_MINION_PUBLIC_KEY_B64={cfg.minion_public_key_b64}",
        "-v", f"{cfg.volume}:/etc/salt/pki/minion",
        cfg.image,
    ]
    printable = " ".join(
        shlex.quote(c) if "PRIVATE_KEY_B64" not in c else "SALT_MINION_PRIVATE_KEY_B64=<redacted>"
        for c in cmd
    )
    print(f"  $ {printable}")
    LOG.debug(f"$ {printable}")
    if dry_run:
        return
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        die("Command not found: docker. Is it installed and on PATH?")
    except subprocess.CalledProcessError as e:
        die(f"Failed to start the minion container (exit {e.returncode}).")


def docker_exec(container: str, args: list, dry_run: bool = False, check: bool = True,
                 timeout: float = None) -> str:
    return run(["docker", "exec", container] + args, dry_run=dry_run, capture=True, check=check,
                timeout=timeout)


MINION_READY_LOG_MARKER = "Minion is ready to receive requests"


STATUS_MASTER_CHECK_TIMEOUT = 8  # seconds


def docker_is_connected(container: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    # The log line below is emitted once, event-driven, the moment the pub/req
    # channels with the master are established - check it first since it's a
    # plain local `docker logs` call that cannot itself hang.
    logs = run(["docker", "logs", container], dry_run=dry_run, capture=True, check=False)
    if MINION_READY_LOG_MARKER in logs:
        return True
    # `salt-call status.master` is a weaker, secondary signal: its answer depends
    # on master_alive_interval being configured on the minion (this image's
    # entrypoint does not set it, so it can under-report even once connected),
    # and - without --local - salt-call itself tries to compile pillar from the
    # master first, which can hang for a long time (or indefinitely) while the
    # minion is still mid-handshake. Run it with a hard timeout so a hang here
    # can never block the overall connect-timeout/poll loop.
    out = docker_exec(
        container,
        ["salt-call", "--local", "--out=newline_values_only", "--retcode-passthrough", "status.master"],
        check=False,
        timeout=STATUS_MASTER_CHECK_TIMEOUT,
    )
    return out.strip().lower() == "true"


PKI_MINION_PEM = "/etc/salt/pki/minion/minion.pem"
PKI_MINION_PUB = "/etc/salt/pki/minion/minion.pub"


def docker_read_minion_pubkey(container: str, dry_run: bool) -> str:
    """Reads the minion's CURRENT public key straight off the running
    container's PKI dir - this is what identifies which trust record to
    rotate server-side (see OpsClient.rotate_minion_key), since minionId is
    never exposed as an input."""
    if dry_run:
        return "-----BEGIN PUBLIC KEY-----\n<dry-run - current key>\n-----END PUBLIC KEY-----\n"
    out = docker_exec(container, ["cat", PKI_MINION_PUB], check=False)
    if not out.strip():
        die(f"Could not read the current public key from '{container}:{PKI_MINION_PUB}'. "
            f"Is the container running and already onboarded?")
    return out


def docker_read_configured_master_fqdn(container: str, dry_run: bool) -> Optional[str]:
    """Best-effort read of the minion's currently configured master FQDN, so
    the rotate flow can warn if the user is about to select a *different*
    master than the one this minion is actually trusted against."""
    if dry_run:
        return None
    out = docker_exec(
        container,
        ["sh", "-c", "grep -m1 '^master:' /etc/salt/minion.d/10-master.conf 2>/dev/null || true"],
        check=False,
    )
    return out.split(":", 1)[1].strip() if out.startswith("master:") else None


def docker_clear_minion_keys(container: str, dry_run: bool) -> None:
    """Removes the minion's PKI files from the (persistent, named or
    bind-mounted) volume while the OLD container still exists to exec into.
    Required before recreating the container with a new keypair -
    docker-entrypoint.sh only seeds SALT_MINION_PRIVATE_KEY_B64/PUBLIC_KEY_B64
    into the PKI dir when minion.pem doesn't already exist, and `docker rm`
    alone does not remove the volume's contents. Runs as root (-u root) -
    see docker_clear_pki_volume() for why (default non-root user, possible
    root-owned bind-mounted host path)."""
    run(["docker", "exec", "-u", "root", container, "rm", "-f", PKI_MINION_PEM, PKI_MINION_PUB],
        dry_run=dry_run, check=False)


def docker_inspect_minion(container: str, dry_run: bool) -> dict:
    """Reads back the image and PKI volume of an already-running container,
    so rotate can recreate it identically (aside from the keypair) without
    asking the user to re-supply --image/--volume from memory."""
    if dry_run:
        return {"image": DEFAULT_IMAGE, "volume": DEFAULT_VOLUME}
    out = run(["docker", "inspect", container], dry_run=dry_run, capture=True, check=True)
    data = json.loads(out)[0]
    image = data["Config"]["Image"]
    volume = None
    for mount in data.get("Mounts", []):
        if mount.get("Destination") == "/etc/salt/pki/minion":
            volume = mount.get("Name") or mount.get("Source")
            break
    if not volume:
        die(f"Could not determine the PKI volume mounted on container '{container}' "
            f"(expected a mount at /etc/salt/pki/minion).")
    return {"image": image, "volume": volume}


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
    minion_key_secret_name: str


def kubectl_upsert_minion_key_secret(namespace: str, secret_name: str,
                                      minion_private_key_b64: str, minion_public_key_b64: str,
                                      dry_run: bool) -> None:
    """
    Creates or updates a Kubernetes Secret holding the minion's keypair -
    the same "existing Secret, created out-of-band, never through Helm
    values" pattern this chart already uses for pillar/vault secrets (Helm
    values end up readable in `helm get values`/release history/Secrets;
    a plain Secret object does not get any less secret for it, but at least
    keeps this key out of the *release* history specifically).
    """
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": secret_name, "namespace": namespace},
        "type": "Opaque",
        "stringData": {
            "private-key-b64": minion_private_key_b64,
            "public-key-b64": minion_public_key_b64,
        },
    }
    run(["kubectl", "apply", "-f", "-"], dry_run=dry_run, capture=False, check=True,
        input_data=json.dumps(manifest), redact_input_in_log=True)


def helm_start(cfg: HelmConfig, dry_run: bool) -> None:
    cmd = [
        "helm", "upgrade", "--install", cfg.release_name, cfg.chart_path,
        "--namespace", cfg.namespace, "--create-namespace",
        "--set", f"salt.master={cfg.master_fqdn}",
        "--set", f"salt.masterFinger={cfg.master_finger}",
        "--set", f"salt.minionId={cfg.minion_id}",
        "--set", f"salt.minionKeySecretName={cfg.minion_key_secret_name}",
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


def kubectl_exec(namespace: str, pod: str, args: list, dry_run: bool = False, check: bool = True,
                  timeout: float = None) -> str:
    return run(["kubectl", "exec", "-n", namespace, pod, "--"] + args,
               dry_run=dry_run, capture=True, check=check, timeout=timeout)


def kubectl_is_connected(namespace: str, pod: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    # See the comments on docker_is_connected() - check the event-driven log
    # marker first (a plain `kubectl logs` call that cannot itself hang), and
    # only fall back to the weaker, hang-prone `status.master` check, bounded
    # by a hard timeout, if the marker hasn't shown up yet.
    logs = run(["kubectl", "logs", "-n", namespace, pod], dry_run=dry_run, capture=True, check=False)
    if MINION_READY_LOG_MARKER in logs:
        return True
    out = kubectl_exec(
        namespace, pod,
        ["salt-call", "--local", "--out=newline_values_only", "--retcode-passthrough", "status.master"],
        check=False,
        timeout=STATUS_MASTER_CHECK_TIMEOUT,
    )
    return out.strip().lower() == "true"


def kubectl_read_minion_pubkey(namespace: str, pod: str, dry_run: bool) -> str:
    """See docker_read_minion_pubkey() - same purpose, Kubernetes path."""
    if dry_run:
        return "-----BEGIN PUBLIC KEY-----\n<dry-run - current key>\n-----END PUBLIC KEY-----\n"
    out = kubectl_exec(namespace, pod, ["cat", PKI_MINION_PUB], check=False)
    if not out.strip():
        die(f"Could not read the current public key from pod '{pod}':{PKI_MINION_PUB}. "
            f"Is it running and already onboarded?")
    return out


def kubectl_read_configured_master_fqdn(namespace: str, pod: str, dry_run: bool) -> Optional[str]:
    """See docker_read_configured_master_fqdn() - same purpose, Kubernetes path."""
    if dry_run:
        return None
    out = kubectl_exec(
        namespace, pod,
        ["sh", "-c", "grep -m1 '^master:' /etc/salt/minion.d/10-master.conf 2>/dev/null || true"],
        check=False,
    )
    return out.split(":", 1)[1].strip() if out.startswith("master:") else None


def kubectl_clear_minion_keys(namespace: str, pod: str, dry_run: bool) -> None:
    """See docker_clear_minion_keys() - same purpose. Necessary when the pki
    volume is a PersistentVolumeClaim (persistence.enabled=true in the Helm
    chart), since a Pod restart alone would keep the OLD keypair on disk; a
    no-op if pki is an emptyDir (deleting the Pod already wipes it)."""
    kubectl_exec(namespace, pod, ["rm", "-f", PKI_MINION_PEM, PKI_MINION_PUB], dry_run=dry_run, check=False)


# --------------------------------------------------------------------------
# Main orchestration
# --------------------------------------------------------------------------

CONFIGURE_TOTAL_STEPS = 6
ROTATE_TOTAL_STEPS = 4
LIST_TOTAL_STEPS = 2


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Configure, rotate, or list salt-minion-vcf instances against a "
                    "VCF Operations-managed Salt master.",
    )
    p.add_argument("--action", choices=["configure", "rotate", "list"],
                   help="What to do: 'configure' onboards a new minion (default), 'rotate' rotates an "
                        "already-onboarded minion's key, 'list' prints trusted minions known to VCF "
                        "Operations. Prompted interactively if omitted.")

    p.add_argument("--ops-host", help="VCF Operations FQDN or IP")
    p.add_argument("--ops-user", help="VCF Operations username")
    p.add_argument("--ops-base-path", default="/suite-api",
                   help="Suite API base path (default: /suite-api)")
    p.add_argument("--insecure", action="store_true",
                   help="Skip TLS certificate verification against VCF Operations")

    p.add_argument("--master-id", help="Salt master ID to use (skips the interactive picker; "
                                        "still validated against GET /api/salt/masters)")
    p.add_argument("--master-page-size", type=int, default=1000,
                   help="Max masters to fetch when listing (default: 1000)")
    p.add_argument("--minion-page-size", type=int, default=1000,
                   help="[list] Max minions to fetch when listing (default: 1000)")
    p.add_argument("--state", choices=["TRUSTED", "REJECTED"],
                   help="[list] Filter minions by trust state")

    p.add_argument("--deployment", choices=["docker", "kubernetes"],
                   help="Where to run the minion")

    p.add_argument("--key-size", type=int, default=2048,
                   help="RSA key size (bits) for the minion's keypair (default: 2048, Salt's own default)")

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
                   help="[k8s] Hash algorithm for master_finger (default: sha256, matches modern Salt). "
                        "The Docker path pre-seeds the master's actual public key instead and does not "
                        "use this.")
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


def pem_finger(pem_text: str, sum_type: str = "sha256") -> str:
    """
    Reproduces Salt's own salt.utils.crypt.pem_finger(): strip the PEM
    header/footer lines, base64-decode the body to raw DER bytes, hash them,
    and format as colon-separated hex pairs - the exact string Salt expects
    for `master_finger` / SALT_MASTER_FINGER. Only used by the Kubernetes/
    Helm path today - the Docker path pre-seeds the master's actual public
    key instead (see helm_start()/docker_start()).
    """
    import hashlib
    lines = [l for l in pem_text.strip().splitlines() if l.strip()]
    if len(lines) < 3:
        raise ValueError("Master public key does not look like a PEM block")
    body = "".join(lines[1:-1])
    der = base64.b64decode(body)
    digest = hashlib.new(sum_type, der).hexdigest()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def onboard_one_minion(client: OpsClient, args: argparse.Namespace, master: dict,
                        deployment: str, defaults: dict, index: int) -> dict:
    """
    Runs steps 3-6 for a single minion and returns a summary dict.

    `index` counts minions onboarded in this session (starting at 1). CLI
    flags for identity-bearing settings (container/volume/release name) are
    only honored on the first minion - a container name, PKI volume, or
    Helm release can't be reused for a second minion without colliding, so
    from the second minion onward this always prompts, with an
    auto-suffixed suggestion ("-2", "-3", ...) to avoid that collision.
    """
    master_id = master["masterId"]
    master_fqdn = master["masterFqdn"]
    master_pubkey_b64 = master["masterPublicKey"]

    # ---------------------------------------------------------------- Step 3
    step(3, CONFIGURE_TOTAL_STEPS, "Generate the minion's RSA keypair")
    minion_private_key_pem, minion_public_key_pem = generate_minion_keypair(
        key_size=args.key_size, dry_run=args.dry_run)
    ok(f"Generated a {args.key_size}-bit RSA keypair (private key never leaves this process)")

    # ---------------------------------------------------------------- Step 4
    step(4, CONFIGURE_TOTAL_STEPS, "Register the minion's public key as trusted")
    if not confirm(f"Register a new minion against master '{master_id}' @ {master_fqdn}?",
                   assume_yes=args.yes):
        die("Aborted by user.", code=0)
    if args.dry_run:
        minion_id = f"ext-minion-<dry-run-{index}>"
        info(f"(dry-run) POST /api/salt/minions {{masterId: {master_id}, minionPublicKey: <PEM>}}")
    else:
        try:
            create_result = client.create_minion(master_id, minion_public_key_pem)
        except OpsApiError as e:
            die(f"Failed to register the minion's key: {e}")
        minion_id = create_result.get("minionId")
        if not minion_id:
            die(f"Registration reported success but returned no minionId: {create_result}")
        key_state = (create_result.get("keyState") or "").upper()
        if key_state and key_state != "TRUSTED":
            die(f"Registration did not result in a trusted key (keyState={key_state}): {create_result}")
    ok(f"Minion registered and trusted: {minion_id}")

    # ---------------------------------------------------------------- Step 5
    step(5, CONFIGURE_TOTAL_STEPS, "Start the minion")
    suffix = "" if index == 1 else f"-{index}"

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
            ("Salt master", f"{master_fqdn} (master pubkey + minion keypair pre-seeded)"),
        ])
        if not confirm("Proceed with these settings?", assume_yes=args.yes):
            die("Aborted by user.", code=0)

        docker_cfg = DockerConfig(
            image=image, container_name=container_name, volume=volume,
            master_fqdn=master_fqdn, master_pubkey_b64=master_pubkey_b64, minion_id=minion_id,
            minion_private_key_b64=base64.b64encode(minion_private_key_pem.encode()).decode(),
            minion_public_key_b64=base64.b64encode(minion_public_key_pem.encode()).decode(),
        )
        docker_start(docker_cfg, dry_run=args.dry_run, assume_yes=args.yes)
        ok(f"Container '{container_name}' started")
        defaults["image"] = image
        pod_name = None
        namespace = None
    else:
        release_name = (args.release_name if index == 1 else None) or prompt(
            "Helm release name", default=f"{DEFAULT_RELEASE_NAME}{suffix}")
        namespace = args.namespace or defaults.get("namespace") or prompt(
            "Namespace", default=DEFAULT_NAMESPACE)
        image_repository = args.image_repository or defaults.get("image_repository") or prompt(
            "Image repository", default=DEFAULT_IMAGE_REPOSITORY)
        image_tag = args.image_tag or defaults.get("image_tag") or prompt(
            "Image tag", default=DEFAULT_IMAGE_TAG)

        master_finger = pem_finger(
            base64.b64decode(master_pubkey_b64).decode("utf-8"), sum_type=args.master_finger_algo)
        minion_key_secret_name = f"{release_name}-minion-key"

        print_summary("Review before starting the minion", [
            ("Deployment", "kubernetes"),
            ("Minion ID", minion_id),
            ("Release name", release_name),
            ("Namespace", namespace),
            ("Image", f"{image_repository}:{image_tag}"),
            ("Salt master", f"{master_fqdn} (master_finger computed)"),
            ("Minion key secret", minion_key_secret_name),
        ])
        if not confirm("Proceed with these settings?", assume_yes=args.yes):
            die("Aborted by user.", code=0)

        kubectl_upsert_minion_key_secret(
            namespace, minion_key_secret_name,
            minion_private_key_b64=base64.b64encode(minion_private_key_pem.encode()).decode(),
            minion_public_key_b64=base64.b64encode(minion_public_key_pem.encode()).decode(),
            dry_run=args.dry_run,
        )
        ok(f"Minion keypair Secret '{minion_key_secret_name}' created/updated in namespace {namespace}")

        helm_cfg = HelmConfig(
            chart_path=args.chart_path, release_name=release_name, namespace=namespace,
            image_repository=image_repository, image_tag=image_tag,
            master_fqdn=master_fqdn, master_finger=master_finger, minion_id=minion_id,
            minion_key_secret_name=minion_key_secret_name,
        )
        helm_start(helm_cfg, dry_run=args.dry_run)
        ok(f"Helm release '{release_name}' installed/upgraded in namespace {namespace}")
        defaults["namespace"] = namespace
        defaults["image_repository"] = image_repository
        defaults["image_tag"] = image_tag
        pod_name = kubectl_get_pod_name(namespace, release_name, dry_run=args.dry_run)
        ok(f"Pod: {pod_name}")

    # ---------------------------------------------------------------- Step 6
    step(6, CONFIGURE_TOTAL_STEPS, "Wait for the minion to connect")

    def _connected() -> bool:
        if deployment == "docker":
            return docker_is_connected(container_name, dry_run=args.dry_run)
        return kubectl_is_connected(namespace, pod_name, dry_run=args.dry_run)

    connected = wait_until(_connected, timeout=args.connect_timeout,
                            check_interval=args.poll_interval,
                            message="Waiting for the minion to connect", dry_run=args.dry_run)
    if not connected:
        die(f"Minion did not connect within {args.connect_timeout}s. "
            f"Trust was already registered (minion ID {minion_id}) - this points at a network/"
            f"connectivity problem, not a trust problem. Check the minion's logs.")
    ok("Minion connected to the Salt master")

    return {"minion_id": minion_id, "deployment": deployment}


# --------------------------------------------------------------------------
# List trusted minions
# --------------------------------------------------------------------------

def list_minions_action(client: OpsClient, args: argparse.Namespace) -> None:
    step(2, LIST_TOTAL_STEPS, "List trusted minions")
    if args.dry_run:
        minions = [{
            "minionId": "<dry-run-minion-id>", "masterId": "salt-master-<dry-run>",
            "keyState": "TRUSTED", "presenceStatus": "PRESENT", "resourceKind": None,
        }]
    else:
        try:
            minions = client.list_minions(state=args.state, page_size=args.minion_page_size)
        except OpsApiError as e:
            die(f"Could not list minions: {e}")

    if not minions:
        info("No trusted minions are known to VCF Operations.")
        return

    print(f"\n{_C.BOLD}Trusted minions{_C.RESET}")
    print(f"{_C.DIM}{'-' * 110}{_C.RESET}")
    print(f"  {'Minion ID':<38} {'Master ID':<28} {'Key State':<10} {'Presence':<10} Resource Kind")
    for m in minions:
        print(f"  {str(m.get('minionId', '')):<38} {str(m.get('masterId', '')):<28} "
              f"{str(m.get('keyState', '')):<10} {str(m.get('presenceStatus', '')):<10} "
              f"{m.get('resourceKind') or '(unknown)'}")
    print(f"{_C.DIM}{'-' * 110}{_C.RESET}")
    ok(f"Listed {len(minions)} minion(s)")


# --------------------------------------------------------------------------
# Rotate an already-onboarded minion's key
# --------------------------------------------------------------------------

def _confirm_master_matches(configured_fqdn: Optional[str], master: dict, assume_yes: bool) -> None:
    """Warns (and asks for confirmation) if the master picked for rotation
    doesn't match the master this minion is actually configured against -
    the rotate API re-associates the minion with whichever masterId is
    passed, so picking the wrong one would silently move the minion, not
    just rotate its key."""
    if not configured_fqdn:
        return
    if configured_fqdn == master.get("masterFqdn"):
        return
    if not confirm(
            f"This minion is currently configured against master '{configured_fqdn}', but you selected "
            f"'{master.get('masterFqdn')}'. Rotating against a different master also RE-ASSOCIATES the "
            f"minion's trust record with it. Continue anyway?", default=False, assume_yes=assume_yes):
        die("Aborted by user.", code=0)


def rotate_minion_docker(client: OpsClient, args: argparse.Namespace) -> None:
    step(2, ROTATE_TOTAL_STEPS, "Identify the minion and read its current key")
    container = args.container_name or prompt("Container name to rotate", default=DEFAULT_CONTAINER_NAME)
    if not args.dry_run and not docker_container_exists(container, args.dry_run):
        die(f"No container named '{container}' found.")

    current_pub = docker_read_minion_pubkey(container, args.dry_run)
    ok(f"Read current public key from '{container}'")
    configured_fqdn = docker_read_configured_master_fqdn(container, args.dry_run)
    if configured_fqdn:
        info(f"This minion is currently configured against master FQDN: {configured_fqdn}")

    master = select_master(client, args)
    _confirm_master_matches(configured_fqdn, master, args.yes)

    step(3, ROTATE_TOTAL_STEPS, "Generate a new keypair and rotate the trusted key")
    new_priv, new_pub = generate_minion_keypair(key_size=args.key_size, dry_run=args.dry_run)
    ok(f"Generated a new {args.key_size}-bit RSA keypair")

    if not confirm(f"Rotate the key for '{container}' against master '{master.get('masterId')}'? "
                    f"The container will be recreated to pick up the new key.", assume_yes=args.yes):
        die("Aborted by user.", code=0)

    if args.dry_run:
        minion_id = "<dry-run-minion-id>"
        info("(dry-run) POST /api/salt/minions/rotate")
    else:
        try:
            result = client.rotate_minion_key(master["masterId"], current_pub, new_pub)
        except OpsApiError as e:
            die(f"Failed to rotate the minion's key: {e}")
        minion_id = result.get("minionId")
        key_state = (result.get("keyState") or "").upper()
        if key_state and key_state != "TRUSTED":
            die(f"Rotation did not result in a trusted key (keyState={key_state}): {result}")
    ok(f"Key rotated and trusted for minion: {minion_id}")

    step(4, ROTATE_TOTAL_STEPS, "Recreate the container with the new key and wait for reconnect")
    inspected = docker_inspect_minion(container, args.dry_run)
    info(f"Recreating '{container}' (image={inspected['image']}, volume={inspected['volume']})")
    # Clear the OLD PKI files while the container still exists to exec into -
    # docker rm does not touch the named volume's contents, and the
    # entrypoint only re-seeds when minion.pem is absent (see
    # docker_clear_minion_keys()).
    docker_clear_minion_keys(container, args.dry_run)
    run(["docker", "rm", "-f", container], dry_run=args.dry_run)

    docker_cfg = DockerConfig(
        image=inspected["image"], container_name=container, volume=inspected["volume"],
        master_fqdn=master["masterFqdn"], master_pubkey_b64=master["masterPublicKey"], minion_id=minion_id,
        minion_private_key_b64=base64.b64encode(new_priv.encode()).decode(),
        minion_public_key_b64=base64.b64encode(new_pub.encode()).decode(),
    )
    docker_start(docker_cfg, dry_run=args.dry_run, assume_yes=True)
    ok(f"Container '{container}' restarted with the new keypair")

    connected = wait_until(lambda: docker_is_connected(container, args.dry_run),
                            timeout=args.connect_timeout, check_interval=args.poll_interval,
                            message="Waiting for the minion to reconnect", dry_run=args.dry_run)
    if not connected:
        die(f"Minion did not reconnect within {args.connect_timeout}s after rotation. "
            f"The key was already rotated (minion ID {minion_id}) - this points at a network/"
            f"connectivity problem, not a trust problem. Check the container's logs.")
    ok("Minion reconnected with the new key")


def rotate_minion_kubernetes(client: OpsClient, args: argparse.Namespace) -> None:
    step(2, ROTATE_TOTAL_STEPS, "Identify the minion and read its current key")
    release_name = args.release_name or prompt("Helm release name to rotate", default=DEFAULT_RELEASE_NAME)
    namespace = args.namespace or prompt("Namespace", default=DEFAULT_NAMESPACE)
    pod_name = kubectl_get_pod_name(namespace, release_name, dry_run=args.dry_run)

    current_pub = kubectl_read_minion_pubkey(namespace, pod_name, args.dry_run)
    ok(f"Read current public key from pod '{pod_name}'")
    configured_fqdn = kubectl_read_configured_master_fqdn(namespace, pod_name, args.dry_run)
    if configured_fqdn:
        info(f"This minion is currently configured against master FQDN: {configured_fqdn}")

    master = select_master(client, args)
    _confirm_master_matches(configured_fqdn, master, args.yes)

    step(3, ROTATE_TOTAL_STEPS, "Generate a new keypair and rotate the trusted key")
    new_priv, new_pub = generate_minion_keypair(key_size=args.key_size, dry_run=args.dry_run)
    ok(f"Generated a new {args.key_size}-bit RSA keypair")

    if not confirm(f"Rotate the key for release '{release_name}' (pod {pod_name}) against master "
                    f"'{master.get('masterId')}'? The Pod will be restarted.", assume_yes=args.yes):
        die("Aborted by user.", code=0)

    if args.dry_run:
        minion_id = "<dry-run-minion-id>"
        info("(dry-run) POST /api/salt/minions/rotate")
    else:
        try:
            result = client.rotate_minion_key(master["masterId"], current_pub, new_pub)
        except OpsApiError as e:
            die(f"Failed to rotate the minion's key: {e}")
        minion_id = result.get("minionId")
        key_state = (result.get("keyState") or "").upper()
        if key_state and key_state != "TRUSTED":
            die(f"Rotation did not result in a trusted key (keyState={key_state}): {result}")
    ok(f"Key rotated and trusted for minion: {minion_id}")

    step(4, ROTATE_TOTAL_STEPS, "Update the Secret, restart the Pod, and wait for reconnect")
    minion_key_secret_name = f"{release_name}-minion-key"
    kubectl_upsert_minion_key_secret(
        namespace, minion_key_secret_name,
        minion_private_key_b64=base64.b64encode(new_priv.encode()).decode(),
        minion_public_key_b64=base64.b64encode(new_pub.encode()).decode(),
        dry_run=args.dry_run,
    )
    ok(f"Minion keypair Secret '{minion_key_secret_name}' updated with the new keypair")

    # Clear any persisted PKI files before restarting - see
    # kubectl_clear_minion_keys() for why this matters when persistence is
    # enabled (PVC-backed pki volume).
    kubectl_clear_minion_keys(namespace, pod_name, args.dry_run)
    run(["kubectl", "delete", "pod", "-n", namespace, pod_name], dry_run=args.dry_run)
    ok(f"Pod '{pod_name}' restart triggered")

    new_pod_name = kubectl_get_pod_name(namespace, release_name, dry_run=args.dry_run)
    connected = wait_until(lambda: kubectl_is_connected(namespace, new_pod_name, args.dry_run),
                            timeout=args.connect_timeout, check_interval=args.poll_interval,
                            message="Waiting for the minion to reconnect", dry_run=args.dry_run)
    if not connected:
        die(f"Minion did not reconnect within {args.connect_timeout}s after rotation. "
            f"The key was already rotated (minion ID {minion_id}) - check pod {new_pod_name}'s logs.")
    ok("Minion reconnected with the new key")


def main() -> None:
    args = build_arg_parser().parse_args()
    log_file = args.log_file or f"vcf-ops-onboard-{datetime.now():%Y%m%d-%H%M%S}.log"
    setup_logging(log_file, verbose=args.verbose)
    LOG.info(f"vcf-ops-onboard started, args={vars(args)}")

    print(f"{_C.BOLD}VCF Operations - External Minion Management{_C.RESET}")
    info(f"Logging full step-by-step detail to: {log_file}")
    if args.dry_run:
        warn("Running in --dry-run mode: nothing will actually be executed.")

    # Chosen up front (before Step 1 is printed) so the "STEP n/total" header
    # can show the right total for whichever action is picked.
    action = args.action or choose(
        "\nWhat would you like to do?", ["configure", "rotate", "list"], default="configure")
    total_steps = {"configure": CONFIGURE_TOTAL_STEPS, "rotate": ROTATE_TOTAL_STEPS,
                   "list": LIST_TOTAL_STEPS}[action]

    # ---------------------------------------------------------------- Step 1
    step(1, total_steps, "Connect to VCF Operations")
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

    if action == "list":
        list_minions_action(client, args)
        print(f"\nFull audit log: {log_file}")
        return

    if action == "rotate":
        deployment = args.deployment or choose(
            "\nWhere is the minion currently running?", ["docker", "kubernetes"], default="docker")
        if deployment == "docker":
            rotate_minion_docker(client, args)
        else:
            rotate_minion_kubernetes(client, args)
        print(f"\n{_C.BOLD}{_C.GREEN}Minion key rotated{_C.RESET}")
        print(f"\nFull audit log: {log_file}")
        return

    # ------------------------------------------------------- action == "configure"
    step(2, total_steps, "List Salt masters and select one")
    master = select_master(client, args)

    # ------------------------------------------------- Steps 3-6 (repeatable)
    deployment = args.deployment or choose(
        "\nWhere should this minion run?", ["docker", "kubernetes"], default="docker")

    onboarded = []
    defaults: dict = {}
    index = 1
    while True:
        result = onboard_one_minion(client, args, master, deployment, defaults, index)
        onboarded.append(result)

        print(f"\n{_C.BOLD}{_C.GREEN}Minion onboarded{_C.RESET}")
        print(f"  Minion ID : {result['minion_id']}")
        print(f"  Master    : {master.get('masterId')} @ {master.get('masterFqdn')}")
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
