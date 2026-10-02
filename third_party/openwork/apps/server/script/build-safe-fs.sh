#!/bin/sh
set -eu
if [ "$(uname -s)" != Darwin ]; then
  echo "safe-fs native boundary requires macOS" >&2
  exit 1
fi
node_bin=$(command -v node)
if [ -z "$node_bin" ]; then
  echo "Node.js headers required for safe-fs build" >&2
  exit 1
fi
node_prefix=$(dirname "$(dirname "$node_bin")")
node_headers="$node_prefix/include/node"
if [ ! -f "$node_headers/node_api.h" ]; then
  echo "Node.js node_api.h missing at $node_headers" >&2
  exit 1
fi
clang -O2 -Wall -Wextra -Werror -bundle -undefined dynamic_lookup \
  -I "$node_headers" src/safe-fs-darwin.c -o src/safe-fs-darwin.node
