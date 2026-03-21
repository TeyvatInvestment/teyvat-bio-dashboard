#!/usr/bin/env python3
"""Generate a bcrypt hash for a password.

Usage:
    python scripts/hash_password.py <password>
    python scripts/hash_password.py  # prompts interactively

Paste the output hash into .streamlit/secrets.toml under the user's password field.
"""

import sys


def main():
    try:
        import bcrypt
    except ImportError:
        print("Install bcrypt: pip install bcrypt")
        sys.exit(1)

    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        import getpass
        password = getpass.getpass("Enter password to hash: ")

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    print(f"\nBcrypt hash:\n{hashed}")
    print("\nPaste this into .streamlit/secrets.toml under the user's password field.")


if __name__ == "__main__":
    main()
