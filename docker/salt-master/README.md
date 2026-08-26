# Salt master image

A Salt master Docker image built from the official onedir distribution via Salt's
[bootstrap script](https://github.com/saltstack/salt-bootstrap). Master-only counterpart to
[`docker/salt-minion`](../salt-minion/README.md) — unlike that image, this one does **not**
install `saltext.kubernetes` or bundle `kubectl`, since execution/state modules run on minions,
not the master, and the master never talks to a cluster API directly.

## Build

Unlike `docker/salt-minion`, this image needs nothing outside its own directory, so it can be
built with that directory as the context:

```bash
docker build -t salt-master docker/salt-master
```

Build args:

| Arg | Default | Purpose |
| --- | --- | --- |
| `SALT_VERSION` | `latest` | Salt version to install, e.g. `3007.1`. `latest` installs the newest stable onedir release. |

## Run

```bash
docker run --rm -p 4505-4506:4505-4506 -e SALT_AUTO_ACCEPT=true salt-master
```

Environment variables (translated into `/etc/salt/master.d/99-env.conf` at container start):

| Variable | Effect |
| --- | --- |
| `SALT_AUTO_ACCEPT` | Sets `auto_accept:` — useful for dev/test setups where manually running `salt-key -a` for every new minion is unwanted. Leave unset for a production master. |
| `SALT_MASTER_ID` | Sets `id:` on the master itself. |

Mount additional config, pillar, or state trees the same way `helm/salt-minion-kubernetes` mounts
them on the minion side, e.g. `-v ./pillar:/srv/pillar:ro -v ./states:/srv/salt:ro`.

With no arguments, the entrypoint starts `salt-master` in the foreground as PID 1. Passing an
explicit command instead (as in the smoke test below) runs that command in the container instead
of the master.

## Smoke test

```bash
docker run --rm salt-master salt-master --version
docker run --rm salt-master salt-run test.arg testing
```
