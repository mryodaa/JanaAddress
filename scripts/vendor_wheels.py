"""Скачать Linux-wheels рантайма в vendor/wheels для офлайн-сборки образа (pip install --no-index).

    python scripts/vendor_wheels.py

Качает под платформу образа (python:3.12-slim, x86_64 glibc) независимо от ОС разработчика.
Для ARM-хоста: --platform manylinux2014_aarch64.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--platform",
        action="append",
        default=None,
        help="платформа wheels (можно несколько), по умолчанию manylinux x86_64",
    )
    args = ap.parse_args(argv)
    platforms = args.platform or ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64"]
    dest = ROOT / "vendor" / "wheels"
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "-r",
        str(ROOT / "requirements.txt"),
        "-d",
        str(dest),
        "--only-binary=:all:",
        "--python-version",
        "3.12",
        "--implementation",
        "cp",
        "--abi",
        "cp312",
        "--abi",
        "abi3",
        "--abi",
        "none",
        "--progress-bar",
        "off",
        "--timeout",
        "60",
        "--retries",
        "10",
    ]
    for p in [*platforms, "any"]:
        cmd += ["--platform", p]
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
