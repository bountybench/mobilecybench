#!/usr/bin/env python3
import hashlib
import sys


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: sha256_file.py <file>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    try:
        print(sha256_file(path))
        return 0
    except Exception as e:
        print(f"error hashing {path}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
