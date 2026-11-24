#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lažni kohya-ss/sd-scripts za testove LoRA trenera (bez GPU-a).

Ispisuje tqdm-ovski napredak (s \\r), "epoch X/Y", avr_loss i na kraju zapiše .safetensors
na STUDIO_LORA_OUTPUT_FILE. Način rada: FAKE_TRAINER_MODE = ok | slow | fail | empty.
FAKE_TRAINER_PID_FILE (+ FAKE_TRAINER_CHILD=1) zapiše PID-ove za test gašenja stabla procesa.
Za temperaturu: FAKE_TRAINER_HEAT_FILE + FAKE_TRAINER_HEAT_AT ("korak:temp,korak:temp").
"""

import os
import sys
import time

mode = os.environ.get("FAKE_TRAINER_MODE", "ok")
out = os.environ.get("STUDIO_LORA_OUTPUT_FILE", "")
total = int(os.environ.get("STUDIO_LORA_TOTAL_STEPS") or 20)
epochs = int(os.environ.get("STUDIO_LORA_EPOCHS") or 2)
delay = float(os.environ.get("FAKE_TRAINER_DELAY") or (0.15 if mode == "slow" else 0.01))
heat_file = os.environ.get("FAKE_TRAINER_HEAT_FILE", "")
heat_at = {}
for part in (os.environ.get("FAKE_TRAINER_HEAT_AT") or "").split(","):
    if ":" in part:
        k, v = part.split(":", 1)
        heat_at[int(k)] = v

pid_file = os.environ.get("FAKE_TRAINER_PID_FILE", "")
if pid_file:
    pids = [str(os.getpid())]
    if os.environ.get("FAKE_TRAINER_CHILD"):
        import subprocess
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        pids.append(str(child.pid))
    with open(pid_file, "w", encoding="utf-8") as fh:
        fh.write("\n".join(pids))
print("ARGS", " ".join(sys.argv[1:]), flush=True)
print("ENV TORCH_BACKENDS_CUDNN_ENABLED=" + os.environ.get("TORCH_BACKENDS_CUDNN_ENABLED", ""), flush=True)
print("ENV PYTORCH_CUDA_ALLOC_CONF=" + os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""), flush=True)
print("caching latents...", flush=True)
time.sleep(delay)
if mode == "fail":
    print("RuntimeError: HIP out of memory. Tried to allocate 20.00 MiB", flush=True)
    sys.exit(1)
per_epoch = max(1, total // max(1, epochs))
step = 0
for ep in range(1, epochs + 1):
    sys.stdout.write(f"\nepoch {ep}/{epochs}\n")
    sys.stdout.flush()
    for _ in range(per_epoch):
        step += 1
        if step > total:
            break
        if heat_file and step in heat_at:
            with open(heat_file, "w", encoding="utf-8") as fh:
                fh.write(heat_at[step])
        pct = int(100 * step / total)
        loss = 0.15 - step * 0.001
        sys.stderr.write(f"\rsteps: {pct:3d}%|####      | {step}/{total} [00:{step:02d}<00:{max(0, total - step):02d},  2.00it/s, avr_loss={loss:.4f}]")
        sys.stderr.flush()
        time.sleep(delay)
sys.stderr.write("\n")
if out and mode != "empty":
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(b"\x08\x00\x00\x00\x00\x00\x00\x00{}      " + os.urandom(64))
elif out:
    open(out, "wb").close()
print("model saved.", flush=True)
