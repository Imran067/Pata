#!/usr/bin/env bash
# Serve Evon on a 24 GB GPU (RTX 4090, RTX PRO 4000 Blackwell) with llama.cpp and a 4-bit GGUF.
# Full precision needs about 70 GB of GPU memory. The Q4_K_M file needs about 21 GB, so it fits.
#
# One-time setup on the GPU machine:
#   1. Check the driver and CUDA:   nvidia-smi   and   nvcc --version
#      Blackwell cards (RTX 50xx, RTX PRO Blackwell) need CUDA 12.8 or newer.
#   2. Build llama.cpp with CUDA:
#        git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp
#        cd ~/llama.cpp && cmake -B build -DGGML_CUDA=ON && cmake --build build --config Release -j
#   3. Download the 4-bit model (about 19 GB) from the community GGUF repository:
#        pip install -U huggingface_hub
#        hf download luminenio/gnani-evon-v3.3-30B-A3B-GGUF --include "*Q4_K_M*" --local-dir ~/models/evon
#      Older huggingface_hub: use "huggingface-cli download" with the same arguments.
#      Check the file list on the model page; adjust the pattern if the name differs.
#
# Every time:
#   tmux new -s evon                 # keeps the server running if SSH drops
#   bash serve_evon_llamacpp.sh      # then detach with Ctrl+B, D
# On your laptop, forward the port and point Pata at it:
#   ssh -N -L 8000:127.0.0.1:8000 you@gpu-machine
#   EVON_BASE_URL=http://localhost:8000/v1      (in .env)
#
# Out of GPU memory? Try CTX=8192, or EXTRA="--n-cpu-moe 4" to keep some expert weights in system RAM.
set -euo pipefail

LLAMA_SERVER="${LLAMA_SERVER:-$HOME/llama.cpp/build/bin/llama-server}"
MODEL="${MODEL:-$(ls "$HOME"/models/evon/*Q4_K_M*.gguf "$HOME"/models/evon/*q4_k_m*.gguf 2>/dev/null | head -n 1 || true)}"
if [ -z "$MODEL" ]; then
  echo "No Q4_K_M .gguf file in ~/models/evon. Download it first (step 3 above), or run with MODEL=/path/to/file.gguf" >&2
  exit 1
fi

exec "$LLAMA_SERVER" -m "$MODEL" --jinja -ngl 99 -c "${CTX:-16384}" \
  --host 127.0.0.1 --port "${PORT:-8000}" ${EXTRA:-}
