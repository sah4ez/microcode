#!/usr/bin/env bash
# Wrapper: makes 'cline' resolve to the node @cline/core shim instead of the
# Bun native binary (crashes on arm64 microsandbox VMs).
# NOTE: resolve shim by absolute path (this script is symlinked as 'cline').
export CLINE_CWD="${CLINE_CWD:-$PWD}"
exec node /Users/aleksandrkozlenkov/git/microcode/todo-run/cline-shim/cline-node-shim.cjs "$@"
