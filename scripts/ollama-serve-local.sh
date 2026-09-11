#!/usr/bin/env bash
set -euo pipefail

ollama_bin="${OLLAMA_BIN:-${HOME}/.local/bin/ollama}"

if [[ ! -x "${ollama_bin}" ]]; then
  echo "Ollama was not found at ${ollama_bin}. See docs/MODEL_BENCHMARK.md." >&2
  exit 1
fi

# The GeForce 940MX was slower than the CPU in the Phase 2 benchmark. These
# settings also avoid depending on a CUDA or Vulkan installation.
export CUDA_VISIBLE_DEVICES=-1
export OLLAMA_VULKAN=0

# Keep the development API private to this computer and disable cloud features.
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_NO_CLOUD=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MODELS="${OLLAMA_MODELS:-${HOME}/.ollama/models}"

exec "${ollama_bin}" serve
