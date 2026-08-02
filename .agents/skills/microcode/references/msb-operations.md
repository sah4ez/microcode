# msb (microsandbox) operations reference

`msb` is the VM runtime microcode drives. The orchestrator calls it for you
during `apply`/`build`/`destroy`, but you need it directly for debugging,
one-shot copies, and manual fixes.

## CLI cheat sheet

```bash
export PATH="$HOME/.microsandbox/bin:$PATH"

msb ps                                    # list VMs + forwarded ports
msb exec <name> --user loki -- bash -lc '...'   # run inside VM as loki
msb exec <name> -- bash -lc '...'               # as root
msb cp <host-path> <name>:<guest-path>          # host → VM
msb cp <name>:<guest-path> <host-path>          # VM → host
msb stop <name>
msb rm -f <name>                          # remove (force)
msb snapshot create <snap> --from <name> --force   # capture
msb snapshot list
msb run --from-snapshot <snap> --name <name> --detach ...   # manual boot
```

## The `msb cp` nesting trap (critical)

`msb cp <dir> vm:/dest` ALWAYS nests `<dir>` inside `/dest`, regardless of a
trailing slash:

```
msb cp ./src vm:/workspace      # → /workspace/src   (WRONG, wanted /workspace)
```

To merge a directory's CONTENTS into a guest dest (true merge like a bind
mount), tar the contents and untar at the dest:

```bash
# host: pack contents (note the dot — contents, not the dir)
COPYFILE_DISABLE=1 tar czf /tmp/seed.tgz --format=ustar -C ./src .

# copy the single tarball (a file, not a dir — no nesting)
msb cp /tmp/seed.tgz vm:/tmp/seed.tgz

# VM: untar at the dest, then clean up
msb exec vm --user root -- bash -c 'tar xzf /tmp/seed.tgz -C /workspace/ && rm /tmp/seed.tgz'

# named volumes are root-owned; chown so loki can write
msb exec vm --user root -- chown -R loki:loki /workspace
```

`COPYFILE_DISABLE=1` avoids macOS xattr noise (`._*` files) in the guest's GNU
tar. `--format=ustar` keeps it portable.

## Named-volume seeding (what the orchestrator does on from_snapshot)

When `from_snapshot` is active, bind mounts become named volumes (msb can't
bind-mount with `--from-snapshot`). The orchestrator seeds each one:

1. **Clear** the guest dest children (so the volume mirrors the host exactly),
   pruning nested mount points:
   ```bash
   find /workspace -mindepth 1 -maxdepth 1 \
     -path /workspace/skills -prune -o -exec rm -rf {} +
   ```
2. **Tar + cp + untar** as above.
3. **chown -R loki:loki** the dest.

This runs on every `apply` (not just the first), so the volume always re-mirrors
the host dir — but it does NOT sync live; mid-session VM edits are invisible to
the host until the next apply.

## Hidden sandbox bug (msb 0.6.8)

`msb rm -f` / `msb list` can fail to see a sandbox, yet `msb create`/`run` fails
with "already exists". Fallback:

```bash
rm -rf ~/.microsandbox/sandboxes/<name>
```

Always do `msb rm -f <name>` + this fallback before `apply`/`build` to clear a
stale sandbox cleanly.

## root-disk rules

- `--root-disk 8G` is valid ONLY for `msb create` (the image-boot path).
- `msb run --from-snapshot` REJECTS it ("requires an OCI image") — the snapshot
  already pins the filesystem; size was set when the snapshot was built.
- Default overlay (~4G) overflows during bootstrap (apt + npm + Go). Always set
  `root_disk: 8G` in the manifest for `build`, and clean caches at the end of
  bootstrap (`apt-get clean`, `npm cache clean --force`, `go clean -cache`).

## /proc scan (pgrep/ps are often missing)

The bookworm-slim VM frequently lacks `pgrep`/`ps`. Scan `/proc` instead:

```bash
msb exec <name> -- bash -lc '
  for p in /proc/[0-9]*; do
    pid=${p##*/}
    cmd=$(tr "\0" " " <"$p/cmdline" 2>/dev/null)
    case "$cmd" in *git-daemon*) echo "pid=$pid: $cmd";; esac
  done
'
```

To kill by pattern:

```bash
msb exec <name> -- bash -lc '
  for p in /proc/[0-9]*; do
    pid=${p##*/}; cmd=$(tr "\0" " " <"$p/cmdline" 2>/dev/null)
    case "$cmd" in *git-daemon*) kill -9 "$pid";; esac
  done
'
```

## Port forwarding

`ports: ["HOST:GUEST"]` maps host localhost → VM eth0. The service inside the VM
MUST bind `0.0.0.0` (not `127.0.0.1`) or the forward looks open but every
request gets an empty reply. Verify from the host:

```bash
nc -z 127.0.0.1 <port>     # should succeed
lsof -nP -iTCP:<port> -sTCP:LISTEN   # msb process listens on host
```

## snapshot save/load (portability)

```bash
msb snapshot save <snap> /path/to/snap.tar   # export
msb snapshot load /path/to/snap.tar          # import on another host
```

## Checking what's on a port inside the VM

```bash
# port 8000 = 0x1F40 in /proc/net/tcp
msb exec <name> -- bash -lc 'grep ":1F40" /proc/net/tcp'
# 00000000:1F40 → listening on 0.0.0.0 (good)
# 0100007F:1F40 → listening on 127.0.0.1 (BAD for port-forward)
```
