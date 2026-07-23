#!/usr/bin/env bash
set -eu

echo "[host]"
hostname

echo "[date]"
date

echo "[memory]"
free -h || true

echo "[disk]"
df -h / /home /home/aiuser /home/aiuser/work 2>/dev/null || df -h

echo "[work usage]"
du -sh /home/aiuser/work 2>/dev/null || true

echo "[cpu]"
lscpu 2>/dev/null | sed -n '1,24p' || true

echo "[gpu]"
nvidia-smi 2>/dev/null || echo "no nvidia-smi"

echo "[python]"
which python || true
python --version || true

