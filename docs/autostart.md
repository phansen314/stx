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

2. **Install the unit** — `make install-unit`, which **symlinks** it:

   ```sh
   cd ~/code/stx && make install-unit
   ```

   Symlinked rather than copied on purpose. A copy drifts from the repo the moment either side is
   edited and nothing tells you; with a link, a repo change reaches the daemon after a
   `daemon-reload`. Machine-specific values (a JDK path, say) go in a **drop-in**
   (`systemctl --user edit stx.service`) — never in the tracked unit, which uses `%h` so it stays
   machine-independent.

3. **Enable + start now:**

   ```sh
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

```sh
cd ~/code/stx && make deploy      # stop → installDist → start
```

**Stop first — do not rebuild under a running daemon.** `installDist` rewrites
`build/install/stx/lib/stx-*.jar` **in place**, and a JVM started earlier has the zip central
directory cached while loading classes lazily. The running daemon therefore keeps serving every
route it has already exercised and fails only on the *first* use of a route it hasn't touched
yet — arbitrarily later, and looking nothing like "you rebuilt under me". `make deploy` exists so
the safe order is the only order you have to remember; `restart` alone does not save you, because
the damage happens during `installDist`, before the restart.

## Notes

- **Config** is via env vars: `STX_PORT` (default 8420) and `XDG_STATE_HOME`. Set them by
  uncommenting the `Environment=` lines in the unit (or via `systemctl --user edit`).
- **Double-start is safe:** the daemon holds an exclusive `~/.local/state/stx/stx.lock`, so a
  second instance (e.g. a manual `bin/stx` while the service runs) exits with code 1 rather
  than corrupting state.
- **Clean stop:** `systemctl --user stop stx.service` sends SIGTERM; the shutdown hook stops the
  server, closes the write actor, and releases the lock. The JVM then exits **143** (128+15), not
  0 — that is what a process killed by SIGTERM reports, cleanly or otherwise. The unit carries
  `SuccessExitStatus=143` so systemd treats it as success; without it every clean stop is recorded
  as `Failed with result 'exit-code'`, which makes `systemctl is-failed` lie and hides a genuine
  crash in the noise. (The alternative — calling `exitProcess(0)` from the shutdown hook — risks
  deadlocking against the shutdown it runs inside, so the fix belongs in the unit.)

## Remove

```sh
systemctl --user disable --now stx.service
rm ~/.config/systemd/user/stx.service   # the symlink; the repo file stays
systemctl --user daemon-reload
```
