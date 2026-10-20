#!/usr/bin/env bash
# Run script for MiniMax-H3 (vLLM-Omni video generation) on NVIDIA RTX A6000 (48 GB).
#
# Source recipe: https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3
# (No H100-validated profile exists in that recipe; the closest documented NVIDIA
#  small-GPU path is the "distributed layerwise offload" profile, validated on
#  RTX 5090 / RTX 4090. That is what this script drives by default.)
#
# Prerequisites (do these once):
#   1. Model access is GATED — accept the terms on the HF model card, then
#        hf auth login   # with an account that has access
#      and download once:
#        ./run_minimax_h3.sh download
#   2. Install vLLM-Omni (needs vllm==0.31.0 + the vllm-omni MAIN checkout, not v0.26.0):
#        uv venv && source .venv/bin/activate
#        uv pip install vllm==0.31.0 --torch-backend=cu130 \
#          --extra-index-url https://wheels.vllm.ai/db9527a46873454610df6dbedf79a36d6bf1a7f6
#        git clone --depth 1 https://github.com/vllm-project/vllm-omni.git
#        cd vllm-omni && uv pip install -e .
#     NOTE: keep torch/torchvision/torchaudio on the cu130 backend (not auto/cu132) so
#     torch (2.13.0+cu130) matches torchaudio (2.11.0+cu130) — torchaudio is EOL at 2.11.
#   3. ffmpeg / ffprobe must be on PATH.
#
# Memory model (BF16, from the recipe) — this is why small cards use offload:
#     FL2VA DiT 66.3 GB | Ref2VA DiT 66.3 GB | Qwen3-VL encoder 51.5 GB
#     video VAE ~10 GB | audio VAE ~0.6 GB
#   A single family (DiT + encoder + VAEs) is ~128 GB; both DiTs ~195 GB.
#   A6000 = 48 GB/card, so a 66.3 GB DiT can never be fully resident per rank
#   ("pure Ulysses replicates the 66.3 GB DiT on every rank" — out for <64 GB cards).
#   => use distributed layerwise offload (DLO) to stream DiT layers from host RAM.
#
# GPU selection — by default the script inspects every GPU's free HBM and runs
#   only on cards with >= MIN_FREE_GB free, so it never grabs a GPU another job
#   is using. Override precedence (first one wins):
#     1. CUDA_VISIBLE_DEVICES=2,3 ./run_minimax_h3.sh        -> honoured verbatim
#     2. NUM_GPUS=2 ./run_minimax_h3.sh                      -> the 2 freest cards
#     3. AUTO_SELECT_GPUS=0                                  -> every GPU (old behaviour)
#   See the current picture with:  ./run_minimax_h3.sh gpus
#
# Profiles (PROFILE env var):
#   dlo      (default) 2+ GPUs, --task-type fl2va|ref2va, DLO streams DiT layers.
#                      Capacity path for small cards. Recommended for A6000.
#   offload  single GPU, model-level CPU offload. Accuracy/memory reference; slow.
#   resident 4+ GPUs, Ulysses SP + ring, no offload. Needs big cards (B300-class);
#                      on 48 GB A6000 this will likely OOM — use only to experiment.
#
# Request-side knobs (sent in extra_params, not serve flags):
#   num_inference_steps=50, flow_shift=12, audio_flow_shift=3.0, fps=24,
#   width/height multiples of 32 (e.g. 1024x576 for A6000, 1344x768 on larger cards).
#   task = t2va | fl2va | ref2va. Endpoints: POST /v1/videos/sync (sync MP4)
#   or POST /v1/videos (async polling).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve the vllm binary. Prefer this repo's own venv (../ from here is the
# repo root) so we never pick up a *foreign* vllm from PATH — e.g. a conda
# env carrying a conflicting plugin (vllm-gr) that rejects vLLM 0.31.0.
venv_dir="${here}/../.venv"
if [ -x "${venv_dir}/bin/vllm" ]; then
  VLLM_BIN="${venv_dir}/bin/vllm"
else
  VLLM_BIN="vllm"
fi

# ---------------------------------------------------------------------------
# Configuration (override via environment)
# ---------------------------------------------------------------------------
MODEL_DIR="${MODEL_DIR:-${here}/MiniMax-H3}"   # gated HF checkpoint, see `download`
PROFILE="${PROFILE:-dlo}"                       # dlo | offload | resident
TASK_TYPE="${TASK_TYPE:-fl2va}"                 # fl2va | ref2va (one DiT family)
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# GPU selection knobs.
MIN_FREE_GB="${MIN_FREE_GB:-8}"        # a GPU with less free HBM than this is "busy"
AUTO_SELECT_GPUS="${AUTO_SELECT_GPUS:-1}"   # 1 = auto-pick free GPUs, 0 = use all GPUs

# DLO capacity knobs (only used by PROFILE=dlo). RTX 5090 (32 GB) uses 20 layers
# @ 1344x768; RTX 4090 (24 GB) uses 12 @ 1024x576. A6000 (48 GB) can keep more
# resident — raise DLO_RESIDENT_LAYERS toward the DiT's layer count if it fits.
DLO_RESIDENT_LAYERS="${DLO_RESIDENT_LAYERS:-20}"
DLO_ATTN_BACKEND="${DLO_ATTN_BACKEND:-CUDNN_ATTN}"   # CUDNN_ATTN | FLASH_ATTN

VLLM_OMNI_VIDEO_SYNC_TIMEOUT="${VLLM_OMNI_VIDEO_SYNC_TIMEOUT:-14400}"
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_OMNI_VIDEO_SYNC_TIMEOUT

# ---------------------------------------------------------------------------
# GPU discovery
# ---------------------------------------------------------------------------
# Print a per-GPU table (index, free MiB, total MiB, busy/free note). Pure report.
list_gpus() {
  local smi line idx free total note
  smi="$(nvidia-smi --query-gpu=index,memory.free,memory.total \
         --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')"
  [ -n "${smi}" ] || { echo "error: no NVIDIA GPUs detected (nvidia-smi returned nothing)" >&2; return 1; }
  printf '%-5s %-12s %-12s %s\n' "GPU" "free MiB" "total MiB" "note"
  while IFS=',' read -r idx free total; do
    note="free"
    [ "${free}" -lt "$((MIN_FREE_GB * 1024))" ] && note="busy (< ${MIN_FREE_GB} GiB)"
    printf '%-5s %-12s %-12s %s\n' "${idx}" "${free}" "${total}" "${note}"
  done <<<"${smi}"
}

# Choose which GPUs to run on and set CUDA_VISIBLE_DEVICES + NUM_GPUS.
select_gpus() {
  # 1. An explicit CUDA_VISIBLE_DEVICES always wins.
  if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
    NUM_GPUS="$(printf '%s' "${CUDA_VISIBLE_DEVICES}" | awk -F, '{print NF}')"
    echo "Using explicit CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES} (${NUM_GPUS} GPU(s))"
    return 0
  fi

  # 2. Otherwise rank every GPU by free HBM (freest first) and take the free ones.
  local smi sorted idx free selected=()
  smi="$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')"
  [ -n "${smi}" ] || { echo "error: no NVIDIA GPUs detected (nvidia-smi returned nothing)" >&2; return 1; }
  sorted="$(printf '%s\n' "${smi}" | sort -t, -k2 -nr)"

  echo "Scanning free HBM (busy = < ${MIN_FREE_GB} GiB):"
  while IFS=',' read -r idx free; do
    if [ "${AUTO_SELECT_GPUS}" = "1" ] && [ "${free}" -lt "$((MIN_FREE_GB * 1024))" ]; then
      printf '  GPU %s: %s MiB free -> skipped (busy)\n' "${idx}" "${free}"
      continue
    fi
    printf '  GPU %s: %s MiB free -> selected\n' "${idx}" "${free}"
    selected+=("${idx}")
  done <<<"${sorted}"

  if [ "${#selected[@]}" -eq 0 ]; then
    echo "error: no GPU has >= ${MIN_FREE_GB} GiB free (set AUTO_SELECT_GPUS=0 to force all)" >&2
    return 1
  fi

  if [ -n "${NUM_GPUS:-}" ]; then
    if [ "${NUM_GPUS}" -gt "${#selected[@]}" ]; then
      echo "error: requested NUM_GPUS=${NUM_GPUS} but only ${#selected[@]} free GPU(s) available" >&2
      return 1
    fi
    selected=("${selected[@]:0:${NUM_GPUS}}")
  else
    NUM_GPUS="${#selected[@]}"
  fi

  CUDA_VISIBLE_DEVICES="$(IFS=,; echo "${selected[*]}")"
  export CUDA_VISIBLE_DEVICES
  echo "Selected GPUs: ${CUDA_VISIBLE_DEVICES} (${NUM_GPUS} GPU(s), freest first)"
}

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
if [ "${1:-}" = "download" ]; then
  command -v hf >/dev/null 2>&1 || { echo "error: 'hf' CLI not found (pip install huggingface_hub)" >&2; exit 1; }
  echo "Downloading MiniMax-H3 (gated) into ${MODEL_DIR} ..."
  exec hf download MiniMaxAI/MiniMax-H3 --local-dir "${MODEL_DIR}"
fi

if [ "${1:-}" = "gpus" ]; then
  list_gpus
  exit 0
fi

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
command -v "${VLLM_BIN}" >/dev/null 2>&1 || { echo "error: '${VLLM_BIN}' not found — install vLLM-Omni first (see header)" >&2; exit 1; }
command -v ffmpeg  >/dev/null 2>&1 || { echo "error: 'ffmpeg' not found on PATH" >&2; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo "error: 'ffprobe' not found on PATH" >&2; exit 1; }
[ -d "${MODEL_DIR}" ] || { echo "error: ${MODEL_DIR} not found — run: $0 download" >&2; exit 1; }

# Profile-implied default GPU count (only applied when NUM_GPUS is not pinned).
case "${PROFILE}" in
  offload) NUM_GPUS="${NUM_GPUS:-1}" ;;
esac

select_gpus || exit 1

# ---------------------------------------------------------------------------
# Build the serve command per profile
# ---------------------------------------------------------------------------
common=(
  --omni
  --host "${HOST}"
  --port "${PORT}"
  --trust-remote-code
  --num-gpus "${NUM_GPUS}"
)

case "${PROFILE}" in
  dlo)
    if [ "${NUM_GPUS}" -lt 2 ]; then
      echo "error: PROFILE=dlo needs >=2 GPUs (got ${NUM_GPUS}); use PROFILE=offload for 1 GPU" >&2
      exit 1
    fi
    args=(
      "${common[@]}"
      --task-type "${TASK_TYPE}"
      --tensor-parallel-size "${NUM_GPUS}"
      --usp 1
      --ring 1
      --text-encoder-tp-size "${NUM_GPUS}"
      --vae-patch-parallel-size "${NUM_GPUS}"
      --vae-parallel-mode tile
      --vae-use-tiling
      --enable-distributed-layerwise-offload
      --dlo-no-use-allgather
      --dlo-resident-layers "${DLO_RESIDENT_LAYERS}"
      --enforce-eager
      --diffusion-attention-backend "${DLO_ATTN_BACKEND}"
    )
    ;;
  offload)
    args=(
      "${common[@]}"
      --task-type "${TASK_TYPE}"
      --enable-cpu-offload
      --diffusion-attention-backend FLASH_ATTN
    )
    ;;
  resident)
    if [ "${NUM_GPUS}" -lt 4 ]; then
      echo "error: PROFILE=resident needs >=4 GPUs (got ${NUM_GPUS})" >&2
      exit 1
    fi
    args=(
      "${common[@]}"
      --task-type "${TASK_TYPE}"
      --usp "${NUM_GPUS}"
      --ring 1
      --vae-patch-parallel-size "${NUM_GPUS}"
      --vae-parallel-mode tile
      --vae-use-tiling
    )
    ;;
  *)
    echo "error: unknown PROFILE '${PROFILE}' (dlo | offload | resident)" >&2
    exit 1
    ;;
esac

# Serve the task's partition subdir (FL2VA/Ref2VA), not the model root. The
# native repo now ships a `modular_model_index.json` that vLLM-Omni's local
# loader misreads as the FastH3 modular format (which then wants a
# `fastvideo_inference.json` that only exists in FastVideo/* releases and
# crashes with FileNotFoundError). Pointing at the partition subdir takes the
# legacy native loader path instead — matching vLLM-Omni's own
# examples/offline_inference/minimax_h3/dlo_lifecycle.py, which serves
# /path/to/MiniMax-H3/FL2VA.
case "${TASK_TYPE}" in
  fl2va)  PARTITION_DIR="FL2VA" ;;
  ref2va) PARTITION_DIR="Ref2VA" ;;
  *)      PARTITION_DIR="" ;;
esac
if [ -n "${PARTITION_DIR}" ] && [ -d "${MODEL_DIR}/${PARTITION_DIR}" ]; then
  SERVE_DIR="${MODEL_DIR}/${PARTITION_DIR}"
else
  SERVE_DIR="${MODEL_DIR}"
fi

echo "Profile: ${PROFILE} | task-type: ${TASK_TYPE} | GPUs: ${NUM_GPUS}"
echo "Serving ${SERVE_DIR} ..."
exec "${VLLM_BIN}" serve "${SERVE_DIR}" "${args[@]}"
