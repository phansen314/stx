# Autostart the stx daemon on login (systemd user service)

The stx daemon (`stx.MainKt`, HTTP on `127.0.0.1:8420`) can be run automatically
whenever you are logged in, using a **systemd user service**. This is login-scoped:
it starts at login and stops at your last logout. No root required.

A ready-to-use unit template lives at
[`packaging/systemd/stx.service`](../packaging/systemd/stx.service). It uses `%h`
(your home dir), so no paths are hard-coded.

## Install

1. **Build the launcher once** (produces `build/install/stx/bin/stx`):

   ```sh
   cd ~/code/stx && ./gradlew installDist
   ```

2. **Install the unit:**

   ```sh
   mkdir -p ~/.config/systemd/user
   cp ~/code/stx/packaging/systemd/stx.service ~/.config/systemd/user/
   ```

3. **Enable + start now:**

   ```sh
   systemctl --user daemon-reload
   systemctl --user enable --now stx.service
   ```

## Verify

```sh
systemctl --user status stx.service
curl -fsS http://127.0.0.1:8420/health && echo OK
journalctl --user -u stx -n 20 --no-pager
```

The startup banner (`stx listening on 127.0.0.1:8420`) and app logs go to the journal
(`journalctl --user -u stx`). The audit journal stays at `~/.local/state/stx/journal.log`.

## Java not found?

The unit relies on `java` (JDK 21) being on PATH. systemd's user manager has a minimal
PATH, so if `status` shows the service failing to find `java`, make Java 21 visible to it —
either a durable drop-in:

```sh
systemctl --user edit stx.service
# add:
# [Service]
# Environment=JAVA_HOME=/path/to/jdk-21
# Environment=PATH=/path/to/jdk-21/bin:/usr/local/bin:/usr/bin:/bin
```

or import your shell PATH once (not persistent across some login setups):

```sh
systemctl --user import-environment PATH
```

## Update after a rebuild

`./gradlew installDist` overwrites the launcher in place — just restart:

```sh
systemctl --user restart stx.service
```

No reinstall needed.

## Notes

- **Config** is via env vars: `STX_PORT` (default 8420) and `XDG_STATE_HOME`. Set them by
  uncommenting the `Environment=` lines in the unit (or via `systemctl --user edit`).
- **Double-start is safe:** the daemon holds an exclusive `~/.local/state/stx/stx.lock`, so a
  second instance (e.g. a manual `bin/stx` while the service runs) exits with code 1 rather
  than corrupting state.
- **Clean stop:** `systemctl --user stop stx.service` sends SIGTERM; the shutdown hook stops
  the server, closes the write actor, and releases the lock (exit 0, no restart).

## Remove

```sh
systemctl --user disable --now stx.service
rm ~/.config/systemd/user/stx.service
systemctl --user daemon-reload
```
