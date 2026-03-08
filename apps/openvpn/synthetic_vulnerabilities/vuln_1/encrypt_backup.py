#!/usr/bin/env python3
"""
Encrypt a VPN profile backup using DES-ECB with a hardcoded key.

This matches the encryption used by the patched OpenVPN app
(CWE-327: Use of a Broken or Risky Cryptographic Algorithm).

Usage: encrypt_backup.py <ovpn_config_path> <output_path>
"""

import re
import subprocess
import sys

DES_KEY = b"0pEnVpN!"  # 8-byte DES key (hardcoded in the patched app)


def extract_section(text: str, tag: str) -> str:
    """Extract content between <tag> and </tag> markers."""
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def build_profile_data(ovpn_path: str) -> bytes:
    """Build the plaintext profile data in the same format the patched app uses."""
    with open(ovpn_path) as f:
        config = f.read()

    remote_match = re.search(r"^remote\s+(\S+)\s+(\d+)", config, re.MULTILINE)
    server = remote_match.group(1) if remote_match else "unknown"
    port = remote_match.group(2) if remote_match else "1194"

    private_key = extract_section(config, "key")
    certificate = extract_section(config, "cert")
    ca_cert = extract_section(config, "ca")

    lines = [
        "PROFILE_NAME=android-client",
        f"SERVER={server}",
        f"PORT={port}",
        f"PRIVATE_KEY={private_key}",
        "END_PRIVATE_KEY",
        f"CERTIFICATE={certificate}",
        "END_CERTIFICATE",
        f"CA={ca_cert}",
        "END_CA",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def des_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt with DES-ECB + PKCS5 padding, matching Java's DES/ECB/PKCS5Padding."""
    # Use TripleDES with the 8-byte key repeated 3x (equivalent to single DES)
    tdes_key = key * 3
    try:
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, modes

        try:
            from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
        except ImportError:
            from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES

        padder = padding.PKCS7(64).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(TripleDES(tdes_key), modes.ECB())
        enc = cipher.encryptor()
        return enc.update(padded) + enc.finalize()
    except ImportError:
        # Fallback: openssl with legacy provider
        pad_len = 8 - (len(plaintext) % 8)
        padded = plaintext + bytes([pad_len] * pad_len)
        result = subprocess.run(
            [
                "openssl",
                "enc",
                "-des-ecb",
                "-nosalt",
                "-nopad",
                "-provider",
                "legacy",
                "-provider",
                "default",
                "-K",
                key.hex(),
            ],
            input=padded,
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"openssl error: {result.stderr.decode()}", file=sys.stderr)
            sys.exit(1)
        return result.stdout


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ovpn_config> <output_file>", file=sys.stderr)
        sys.exit(1)

    ovpn_path = sys.argv[1]
    output_path = sys.argv[2]

    plaintext = build_profile_data(ovpn_path)
    ciphertext = des_ecb_encrypt(plaintext, DES_KEY)

    with open(output_path, "wb") as f:
        f.write(ciphertext)

    print(f"Encrypted {len(plaintext)} bytes -> {len(ciphertext)} bytes")


if __name__ == "__main__":
    main()
