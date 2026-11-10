#!/usr/bin/env bash
# Serve Gnani Evon (gnani-evon-v3.3-30B-A3B) with an OpenAI-compatible API.
#
# Needs an NVIDIA GPU with about 80 GB of memory for BF16 (A100, H100 or H200), and vLLM 0.12 or newer:
#   pip install "vllm>=0.12"
# The first run downloads about 60 GB of weights from Hugging Face.
#
# Then, on the machine running Pata, set in .env:
#   EVON_BASE_URL=http://<this-machine>:8000/v1
#
# Smaller GPU? Try the community GGUF quantisation with llama.cpp instead:
#   llama-server -m <gnani-evon-v3.3 GGUF file> --jinja -c 16384 --port 8000
# and check that "enable_thinking": false really turns reasoning off with that build.
set -euo pipefail

MODEL="${MODEL:-gnani/gnani-evon-v3.3-30B-A3B}"
PORT="${PORT:-8000}"
MAX_LEN="${MAX_LEN:-16384}"

exec vllm serve "$MODEL" \
  --served-model-name model \
  --trust-remote-code \
  --max-model-len "$MAX_LEN" \
  --reasoning-parser nano_v3 \
  --port "$PORT"
