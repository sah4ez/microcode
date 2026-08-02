//go:build tools

// This file pins build/codegen tool dependencies in go.mod via blank imports.
// The "tools" build tag excludes it from normal builds, so the pinned modules
// never end up in the compiled binary.
//
// github.com/seniorGolang/tg/v3 is the contract-first codegen toolchain that
// generates internal/transport (`tg server -o internal/transport`). In tg v3 the
// generator output is self-contained Go (go-fiber + zerolog), so the framework
// is a codegen-time dependency only: it is pinned here, not imported by the
// service at runtime. Pinning its module version documents which toolchain
// produced internal/transport.
package tools

import (
	_ "github.com/seniorGolang/tg/v3/skills" // pin tg/v3 module version for codegen
)
