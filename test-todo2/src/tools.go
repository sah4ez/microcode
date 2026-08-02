//go:build tools

// This file pins build/codegen tool dependencies in go.mod via blank imports.
// The "tools" build tag excludes it from normal builds, so the pinned modules
// never end up in the compiled binary.
//
// github.com/seniorGolang/tg/v3 is the contract-first codegen toolchain that
// generates internal/transport (`tg server -o internal/transport`). In tg v3 the
// generator output is self-contained Go (go-fiber + zerolog), so the framework
// is a codegen-time dependency only: it is pinned here via a build-tagged blank
// import of the tg/v3 CLI entrypoint (the sole importable package of the module)
// so that `go mod tidy` keeps it as a real dependency of this module, while the
// "tools" build tag keeps it — and tg's transitive CLI graph — out of the runtime
// binary. The generated transport (internal/transport) never imports tg/v3.
package tools

import (
	_ "github.com/seniorGolang/tg/v3/cmd/tg" // pin tg/v3 CLI toolchain version
)

