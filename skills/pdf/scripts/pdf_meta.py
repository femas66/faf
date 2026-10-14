#!/usr/bin/env python3
"""Inspect/modify document metadata and manage embedded file attachments in PDF documents."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    import pypdf
except ImportError as err:
    print(
        f"Error: Required library 'pypdf' is missing ({err}).\n"
        f"Install it via: pip install pypdf",
        file=sys.stderr,
    )
    sys.exit(1)


def get_metadata(pdf_path: str) -> dict[str, Any]:
    reader = pypdf.PdfReader(pdf_path)
    meta = reader.metadata or {}
    return {
        "file": pdf_path,
        "title": meta.get("/Title"),
        "author": meta.get("/Author"),
        "subject": meta.get("/Subject"),
        "creator": meta.get("/Creator"),
        "producer": meta.get("/Producer"),
        "keywords": meta.get("/Keywords"),
        "creation_date": str(meta.get("/CreationDate", "")),
        "modification_date": str(meta.get("/ModDate", "")),
    }


def set_metadata(
    pdf_path: str,
    output_path: str,
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    keywords: str | None = None,
    creator: str | None = None,
) -> None:
    reader = pypdf.PdfReader(pdf_path)
    writer = pypdf.PdfWriter(clone_from=reader)

    new_meta: dict[str, str] = {}
    if title is not None:
        new_meta["/Title"] = title
    if author is not None:
        new_meta["/Author"] = author
    if subject is not None:
        new_meta["/Subject"] = subject
    if keywords is not None:
        new_meta["/Keywords"] = keywords
    if creator is not None:
        new_meta["/Creator"] = creator

    writer.add_metadata(new_meta)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f_out:
        writer.write(f_out)


def attach_file(pdf_path: str, output_path: str, attach_filepath: str) -> None:
    if not os.path.isfile(attach_filepath):
        raise FileNotFoundError(f"Attachment file '{attach_filepath}' does not exist.")

    reader = pypdf.PdfReader(pdf_path)
    writer = pypdf.PdfWriter(clone_from=reader)

    fname = os.path.basename(attach_filepath)
    with open(attach_filepath, "rb") as f_att:
        file_bytes = f_att.read()

    writer.add_attachment(fname, file_bytes)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f_out:
        writer.write(f_out)


def list_attachments(pdf_path: str) -> list[dict[str, Any]]:
    reader = pypdf.PdfReader(pdf_path)
    attachments_dict = reader.attachments
    results = []

    for name, data_list in attachments_dict.items():
        for item in data_list:
            size_bytes = len(item) if isinstance(item, (bytes, bytearray)) else 0
            results.append({"name": name, "size_bytes": size_bytes})

    return results


def extract_attachments(pdf_path: str, target_dir: str) -> list[str]:
    reader = pypdf.PdfReader(pdf_path)
    attachments_dict = reader.attachments
    os.makedirs(target_dir, exist_ok=True)
    extracted = []

    for name, data_list in attachments_dict.items():
        for idx, item in enumerate(data_list):
            out_name = name if len(data_list) == 1 else f"{idx}_{name}"
            out_path = os.path.join(target_dir, out_name)
            with open(out_path, "wb") as f_out:
                if isinstance(item, (bytes, bytearray)):
                    f_out.write(item)
            extracted.append(out_path)

    return extracted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect, set PDF metadata, and manage embedded file attachments."
    )
    parser.add_argument("pdf", help="Path to input PDF file.")
    parser.add_argument("-o", "--output", help="Path for output PDF file when modifying.")

    # Metadata flags
    parser.add_argument("--get-meta", action="store_true", help="Print document metadata as JSON.")
    parser.add_argument("--set-meta", action="store_true", help="Update document metadata (requires -o).")
    parser.add_argument("--title", help="Document Title.")
    parser.add_argument("--author", help="Document Author.")
    parser.add_argument("--subject", help="Document Subject.")
    parser.add_argument("--keywords", help="Document Keywords.")
    parser.add_argument("--creator", help="Document Creator Application.")

    # Attachment flags
    parser.add_argument("--attach", help="Path of local file to embed into PDF (requires -o).")
    parser.add_argument("--list-attachments", action="store_true", help="List embedded file attachments.")
    parser.add_argument("--extract-attachments", help="Target directory to extract embedded attachments into.")

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Error: File '{args.pdf}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        if args.set_meta:
            if not args.output:
                print("Error: --set-meta requires -o / --output path.", file=sys.stderr)
                sys.exit(1)
            set_metadata(
                args.pdf,
                args.output,
                title=args.title,
                author=args.author,
                subject=args.subject,
                keywords=args.keywords,
                creator=args.creator,
            )
            print(f"Successfully updated metadata in: {args.output}")

        elif args.attach:
            if not args.output:
                print("Error: --attach requires -o / --output path.", file=sys.stderr)
                sys.exit(1)
            attach_file(args.pdf, args.output, args.attach)
            print(f"Successfully attached '{args.attach}' into: {args.output}")

        elif args.list_attachments:
            atts = list_attachments(args.pdf)
            print(json.dumps({"file": args.pdf, "attachments_count": len(atts), "attachments": atts}, indent=2))

        elif args.extract_attachments:
            extracted = extract_attachments(args.pdf, args.extract_attachments)
            print(f"Extracted {len(extracted)} attachment(s) to '{args.extract_attachments}/':")
            for p in extracted:
                print(f"  - {p}")

        else:
            # Default action: get metadata
            meta = get_metadata(args.pdf)
            print(json.dumps(meta, indent=2))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
