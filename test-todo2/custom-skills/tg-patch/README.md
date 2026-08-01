# tg v3 race-condition patch

`tg pkg add` (v3.0.x) has a **race condition** in its download progress wrapper
that produces a deterministic `Failed to extract archive ...-skills.tar.gz: EOF`
error inside microsandbox VMs (and likely other environments with slightly
different scheduler timing than the author's CI).

## Root cause

`internal/installer/managers/installation/install.go` → `downloadWithProgress()`
spawns the real download in a goroutine that writes to a `progress` channel and
returns the result on `errChan`. When `errChan` receives a `nil` (download
finished OK), the outer loop did:

```go
case downloadErr = <-errChan:
    if downloadErr != nil { return downloadErr }
    select {
    case _, ok := <-progressChan:
    case <-ctx.Done():
        return ctx.Err()
    default:          // <-- BUG: returns before close(progress) has flushed the file
    }
    return            // success reported while the file on disk is still incomplete
```

The `default:` arm returns *before* `DownloadWithProgress` has executed
`close(progress)` (which happens right before its return). So `extractArchive`
opens a **truncated** file and `gzip.Reader` / `tar.Next()` hit EOF. It is a
timing race: on the author's host the goroutine finishes first, so `tg pkg add`
appears to work; under the microsandbox network layer the timing differs and the
race fires every time.

## Fix

Remove the `default:` branch and loop until `progressChan` is closed (the
guarantee that `DownloadWithProgress` reached `close(progress)` → file fully
flushed):

```go
case downloadErr = <-errChan:
    if downloadErr != nil { return downloadErr }
    for {
        select {
        case _, ok := <-progressChan:
            if !ok { bar.SetCurrent(100); bar.Print(); return }
        case <-ctx.Done():
            return ctx.Err()
        }
    }
```

See `install.go.patched` (the patched full file) and the upstream issue for the
minimal diff.

## Reproduce / verify

```bash
# file is valid (curl downloads it fully, md5 matches):
URL="https://github.com/seniorGolang/tgp-go/releases/download/v1.0.8/astg-skills.tar.gz"
curl -fsSL "$URL" | md5sum      # c5e726c76a2a53c1ea28119c31ce8803 (deterministic)
gzip -t <(curl -fsSL "$URL")    # OK

# but unpatched tg:
tg pkg add https://github.com/seniorGolang/tgp-go:astg   # → EOF every time
```

## Building a patched tg

```bash
git clone --branch v3.0.5 https://github.com/seniorGolang/tg
cp install.go.patched tg/internal/installer/managers/installation/install.go
cd tg && GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o tg ./cmd/tg
```

The patched binary is what makes `tg pkg add :astg` / `:server` succeed inside
the VM (verified — both plugins install and `tg server -o transport` generates a
full fiber transport from a `// @tg` contract).
