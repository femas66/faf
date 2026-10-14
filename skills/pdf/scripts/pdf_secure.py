#!/usr/bin/env python3
"""Encrypt or decrypt PDF documents using standard AES-256 / AES-128 algorithms."""

from __future__ import annotations

import argparse
import os
import sys

try:
    import pypdf
except ImportError as err:
    print(
        f"Error: Required library 'pypdf' is missing ({err}).\n"
        f"Install it via: pip install pypdf",
        file=sys.stderr,
    )
    sys.exit(1)


def encrypt_pdf(
    input_path: str,
    output_path: str,
    user_password: str,
    owner_password: str | None = None,
    algorithm: str = "AES-256",
) -> None:
    reader = pypdf.PdfReader(input_path)
    writer = pypdf.PdfWriter(clone_from=reader)
    writer.encrypt(
        user_password=user_password,
        owner_password=owner_password or user_password,
        algorithm=algorithm,
    )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f_out:
        writer.write(f_out)


def decrypt_pdf(input_path: str, output_path: str, password: str) -> None:
    reader = pypdf.PdfReader(input_path)
    if not reader.is_encrypted:
        print(f"Notice: '{input_path}' is not encrypted. Copying as is.", file=sys.stderr)
        writer = pypdf.PdfWriter(clone_from=reader)
    else:
        decrypt_result = reader.decrypt(password)
        if decrypt_result == 0:
            raise ValueError("Decryption failed: Incorrect password.")
        writer = pypdf.PdfWriter(clone_from=reader)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f_out:
        writer.write(f_out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt or decrypt PDF documents with password security."
    )
    parser.add_argument("pdf", help="Path to input PDF file.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--encrypt", action="store_true", help="Encrypt the PDF.")
    group.add_argument("--decrypt", action="store_true", help="Decrypt the PDF.")

    parser.add_argument("-o", "--output", required=True, help="Path for output PDF.")
    parser.add_argument("--user-password", help="Password for user access (opening/reading the document).")
    parser.add_argument("--owner-password", help="Optional owner/admin password (for editing permissions).")
    parser.add_argument("--password", help="Password to decrypt (used with --decrypt).")
    parser.add_argument(
        "--algorithm",
        default="AES-256",
        choices=["AES-256", "AES-128"],
        help="Encryption cipher algorithm (default: AES-256).",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Error: File '{args.pdf}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        if args.encrypt:
            pwd = args.user_password or args.password
            if not pwd:
                print("Error: --user-password (or --password) is required for encryption.", file=sys.stderr)
                sys.exit(1)
            encrypt_pdf(
                args.pdf,
                args.output,
                user_password=pwd,
                owner_password=args.owner_password,
                algorithm=args.algorithm,
            )
            print(f"Successfully encrypted document: {args.output}")

        elif args.decrypt:
            pwd = args.password or args.user_password
            if not pwd:
                print("Error: --password is required for decryption.", file=sys.stderr)
                sys.exit(1)
            decrypt_pdf(args.pdf, args.output, password=pwd)
            print(f"Successfully decrypted document: {args.output}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
