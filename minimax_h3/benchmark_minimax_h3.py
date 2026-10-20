#!/usr/bin/env python3
"""Benchmark a running MiniMax-H3 (vLLM-Omni) video server.

Drives ``POST /v1/videos/sync`` and reports client E2E latency plus the
server-reported timings returned in the response headers:

    X-Inference-Time-S   server-side E2E (encode + denoise + decode + MP4 encode)
    X-Stage-Durations    JSON dict of per-phase seconds (encode/denoise/decode/...)
    X-Peak-Memory-MB     peak GPU memory used by the request

Run against the server started by run_minimax_h3.sh, e.g.:

    ./benchmark_minimax_h3.py --url http://127.0.0.1:8000/v1/videos/sync \
        --task t2va --num-requests 3 --warmup 1

Warmup requests are excluded from all statistics. By default outputs are
discarded (not written to disk); pass --save-output-dir to keep the MP4s.

Requires: requests. Run it with an interpreter that has ``requests`` installed,
e.g. from the kv_fast_fusion venv:

    /path/to/kv_fast_fusion/.venv/bin/python benchmark_minimax_h3.py
    # or, if this repo's own .venv has requests installed:
    ../.venv/bin/python benchmark_minimax_h3.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------

_TASK_DEFAULTS = {
    "t2va": "A cinematic shot of a lighthouse at dusk, waves crashing, seagulls overhead",
    "fl2va": "A man stands beside a yellow car at night; it drives away and he follows it with his eyes",
    "ref2va": "A white cat sits on a beige couch and slowly looks toward the camera",
}


def build_form(args: argparse.Namespace, seed: int) -> tuple[dict[str, object], dict[str, tuple]]:
    """Return (fields, files) for a requests.post(...)."""
    extra = {"task": args.task, "duration": args.duration, "audio_flow_shift": args.audio_flow_shift}
    if args.task == "fl2va" and args.frame_indices:
        extra["frame_indices"] = [int(i) for i in args.frame_indices.split(",")]

    fields: dict[str, object] = {
        "prompt": args.prompt,
        "fps": args.fps,
        "num_inference_steps": args.steps,
        "flow_shift": args.flow_shift,
        "seed": seed,
        "extra_params": json.dumps(extra, separators=(",", ":")),
    }
    # width/height only sent when explicitly set (FL2VA may prefer auto from
    # the reference frame when omitted).
    if args.width is not None:
        fields["width"] = args.width
    if args.height is not None:
        fields["height"] = args.height
    if args.aspect_ratio:
        fields["aspect_ratio"] = args.aspect_ratio

    files: dict[str, tuple] = {}
    if args.reference:
        data = Path(args.reference).read_bytes()
        if args.task == "fl2va" and args.frame_indices:
            files["input_references"] = ("ref.png", data, "image/png")
        else:
            files["input_reference"] = ("ref.png", data, "image/png")
    return fields, files


def send_one(args: argparse.Namespace, seed: int) -> dict[str, object]:
    """Send one request; returns a record dict (never raises)."""
    fields, files = build_form(args, seed)
    record: dict[str, object] = {"seed": seed, "ok": False}
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            args.url,
            data=fields,
            files=files or None,
            timeout=args.timeout,
        )
        record["e2e_s"] = time.perf_counter() - t0
        record["status"] = resp.status_code
        if resp.status_code == 200:
            record["ok"] = True
            record["bytes"] = len(resp.content)
            record["inference_s"] = _float_header(resp, "X-Inference-Time-S")
            record["peak_memory_mb"] = _float_header(resp, "X-Peak-Memory-MB")
            record["stages"] = _json_header(resp, "X-Stage-Durations")
            if args.save_output_dir:
                record["content"] = resp.content
        else:
            record["error"] = resp.text[:500]
    except requests.Timeout:
        record["e2e_s"] = time.perf_counter() - t0
        record["error"] = f"timeout after {args.timeout}s"
    except requests.RequestException as exc:  # network/connection errors
        record["e2e_s"] = time.perf_counter() - t0
        record["error"] = str(exc)
    return record


def _float_header(resp: requests.Response, name: str) -> float | None:
    try:
        return float(resp.headers[name])
    except (KeyError, ValueError):
        return None


def _json_header(resp: requests.Response, name: str) -> dict[str, float] | None:
    try:
        val = json.loads(resp.headers[name])
        return {str(k): float(v) for k, v in val.items()}
    except (KeyError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(records: list[dict[str, object]]) -> dict[str, object]:
    ok = [r for r in records if r.get("ok")]
    e2e = [r["e2e_s"] for r in ok if isinstance(r.get("e2e_s"), float)]
    inf = [r["inference_s"] for r in ok if isinstance(r.get("inference_s"), float)]
    mem = [r["peak_memory_mb"] for r in ok if isinstance(r.get("peak_memory_mb"), float)]

    stage_names: set[str] = set()
    for r in ok:
        if isinstance(r.get("stages"), dict):
            stage_names.update(r["stages"].keys())
    stages: dict[str, list[float]] = {}
    for r in ok:
        sd = r.get("stages")
        if isinstance(sd, dict):
            for k, v in sd.items():
                stages.setdefault(k, []).append(float(v))

    def agg(vals: list[float]) -> dict[str, float]:
        return {
            "n": len(vals),
            "mean": statistics.fmean(vals) if vals else float("nan"),
            "min": min(vals) if vals else float("nan"),
            "max": max(vals) if vals else float("nan"),
            "p50": _pct(vals, 0.50),
            "p90": _pct(vals, 0.90),
            "p99": _pct(vals, 0.99),
        }

    out: dict[str, object] = {
        "completed": len(ok),
        "failed": len(records) - len(ok),
        "e2e_s": agg(e2e),
        "inference_s": agg(inf),
        "peak_memory_mb": agg(mem),
        "stages": {k: agg(v) for k, v in sorted(stages.items())},
    }
    return out


def _fmt_agg(name: str, a: dict[str, float]) -> str:
    return (
        f"  {name:<18} n={a['n']:<3} mean={a['mean']:>8.2f}  "
        f"min={a['min']:>8.2f}  max={a['max']:>8.2f}  "
        f"p50={a['p50']:>8.2f}  p90={a['p90']:>8.2f}  p99={a['p99']:>8.2f}"
    )


def print_report(summary: dict[str, object], total_wall_s: float, throughput: float) -> None:
    print("\n==================== MiniMax-H3 benchmark ====================")
    print(f"completed={summary['completed']}  failed={summary['failed']}  "
          f"total_wall={total_wall_s:.1f}s  throughput={throughput:.3f} req/s")
    print(_fmt_agg("e2e (client)", summary["e2e_s"]))
    print(_fmt_agg("inference (server)", summary["inference_s"]))
    for k, a in summary["stages"].items():
        print(_fmt_agg(f"stage[{k}]", a))
    print(_fmt_agg("peak_memory_mb", summary["peak_memory_mb"]))
    print("==============================================================")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark MiniMax-H3 vLLM-Omni server")
    p.add_argument("--url", default="http://127.0.0.1:8000/v1/videos/sync")
    p.add_argument("--task", choices=["t2va", "fl2va", "ref2va"], default="t2va")

    p.add_argument("--prompt", default=None, help="default per task if unset")
    p.add_argument("--width", type=int, default=1024)
    p.add_argument("--height", type=int, default=576)
    p.add_argument("--aspect-ratio", default="16:9")
    p.add_argument("--fps", type=float, default=24)
    p.add_argument("--steps", type=int, default=50, help="num_inference_steps")
    p.add_argument("--flow-shift", type=float, default=12)
    p.add_argument("--duration", type=float, default=4.0)
    p.add_argument("--audio-flow-shift", type=float, default=3.0)

    p.add_argument("--reference", default=None, help="image for fl2va/ref2va")
    p.add_argument("--frame-indices", default=None,
                   help="comma list for fl2va first/last conditioning, e.g. 0,-1")

    p.add_argument("--num-requests", type=int, default=3, help="measured (non-warmup) requests")
    p.add_argument("--warmup", type=int, default=1, help="warmup requests, excluded from stats")
    p.add_argument("--concurrency", type=int, default=1, help="parallel request workers")
    p.add_argument("--seed", type=int, default=1101, help="base seed; incremented per request")
    p.add_argument("--timeout", type=float, default=3600, help="per-request timeout (s)")

    p.add_argument("--save-output-dir", default=None, help="write MP4s here (default: discard)")
    p.add_argument("--json", default=None, help="dump per-request records to this file")
    p.add_argument("--dry-run", action="store_true", help="print one request and exit")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.prompt is None:
        args.prompt = _TASK_DEFAULTS[args.task]

    if args.dry_run:
        fields, files = build_form(args, args.seed)
        print("POST", args.url)
        for k, v in fields.items():
            print(f"  {k} = {v}")
        for k, v in files.items():
            print(f"  {k} = <file {len(v[1])} bytes, {v[2]}>")
        return 0

    total = args.warmup + args.num_requests
    seeds = [args.seed + i for i in range(total)]

    t_start = time.perf_counter()
    records: list[dict[str, object]] = [None] * total  # type: ignore[list-item]

    # Worker pool: each worker grabs the next index and sends one request.
    idx_lock = threading.Lock()
    next_idx = 0

    def worker() -> None:
        nonlocal next_idx
        while True:
            with idx_lock:
                i = next_idx
                next_idx += 1
            if i >= total:
                return
            records[i] = send_one(args, seeds[i])

    n_workers = min(args.concurrency, total)
    threads = [threading.Thread(target=worker) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total_wall = time.perf_counter() - t_start

    warmup, measured = records[: args.warmup], records[args.warmup:]
    summary = summarize(measured)
    throughput = summary["completed"] / total_wall if total_wall > 0 else float("nan")

    # Per-request table (measured only).
    print(f"\n{'req':>4} {'seed':>6} {'status':>6} {'e2e_s':>9} {'infer_s':>9} "
          f"{'peak_mb':>9}  stages")
    for idx, r in enumerate(measured):
        stages = ""
        if isinstance(r.get("stages"), dict):
            stages = " ".join(f"{k}={v:.2f}" for k, v in sorted(r["stages"].items()))
        infer = f"{r.get('inference_s'):.2f}" if isinstance(r.get("inference_s"), float) else "-"
        peak = f"{r.get('peak_memory_mb'):.1f}" if isinstance(r.get("peak_memory_mb"), float) else "-"
        status = r.get("status", "ERR")
        if not r.get("ok"):
            print(f"{idx:>4} {r['seed']:>6} {status!s:>6} {r.get('e2e_s', float('nan')):>9.2f} "
                  f"{infer:>9} {peak:>9}  ERROR: {r.get('error', '')[:120]}")
        else:
            print(f"{idx:>4} {r['seed']:>6} {status!s:>6} {r['e2e_s']:>9.2f} "
                  f"{infer:>9} {peak:>9}  {stages}")

    print_report(summary, total_wall, throughput)

    if args.save_output_dir:
        out = Path(args.save_output_dir)
        out.mkdir(parents=True, exist_ok=True)
        saved = 0
        for idx, r in enumerate(measured):
            if r.get("ok") and isinstance(r.get("content"), bytes):
                (out / f"out_{idx:03d}_seed{r['seed']}.mp4").write_bytes(r["content"])
                saved += 1
        print(f"saved {saved} MP4(s) -> {out}")
    if args.json:
        Path(args.json).write_text(json.dumps({"args": vars(args), "records": records}, indent=2))
        print(f"per-request records -> {args.json}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
