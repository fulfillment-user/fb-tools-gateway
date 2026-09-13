#!/usr/bin/env python3
"""
Run locally (not deployed) to turn a plaintext password into the bcrypt hash
that goes in config.yaml. Never commit a plaintext password to the repo --
only the hash.

Usage: python3 hash_password.py "the-persons-password"
"""
import sys

import bcrypt

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 hash_password.py <plaintext-password>")
    pw = sys.argv[1].encode()
    print(bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode())
