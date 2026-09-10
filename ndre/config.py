"""CLI argument parsing and run configuration for NDRE."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field


@dataclass
class Config:
    netbox_url: str
    netbox_token: str
    tag: str
    tls_verify: bool
    title: str
    frontmatter: list[str] = field(default_factory=list)
    output: str = "ndre-export.md"
    pdf: bool = False
    pdf_output: str | None = None


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        prog="ndre",
        description=(
            "Export Netbox data needed to reconstruct core network "
            "connectivity from scratch during disaster recovery."
        ),
    )
    parser.add_argument(
        "--netbox-url",
        default=os.environ.get("NETBOX_URL"),
        help="Netbox base URL (or set NETBOX_URL)",
    )
    parser.add_argument(
        "--netbox-token",
        default=os.environ.get("NETBOX_TOKEN"),
        help="Netbox API token (or set NETBOX_TOKEN)",
    )
    parser.add_argument(
        "--tag",
        default=os.environ.get("NDRE_TAG", "ndre"),
        help="Tag used to select objects for export (default: ndre)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=os.environ.get("NETBOX_INSECURE", "").lower() in ("1", "true", "yes"),
        help="Disable TLS certificate verification",
    )
    parser.add_argument(
        "--title",
        default="Disaster Recovery Export",
        help="Document title",
    )
    parser.add_argument(
        "--frontmatter",
        action="append",
        default=[],
        metavar="FILE",
        help="Markdown file to include verbatim near the top of the document; "
        "may be given multiple times, each contributes one or more sections",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="ndre-export.md",
        help="Output Markdown file path (default: ndre-export.md)",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also render the export to PDF (requires the 'pdf' extra: "
        'pip install -e ".[pdf]")',
    )
    parser.add_argument(
        "--pdf-output",
        default=None,
        metavar="FILE",
        help="PDF output path (default: same name as --output with a .pdf extension)",
    )

    args = parser.parse_args(argv)

    if not args.netbox_url:
        parser.error("--netbox-url is required (or set NETBOX_URL)")
    if not args.netbox_token:
        parser.error("--netbox-token is required (or set NETBOX_TOKEN)")

    return Config(
        netbox_url=args.netbox_url,
        netbox_token=args.netbox_token,
        tag=args.tag,
        tls_verify=not args.insecure,
        title=args.title,
        frontmatter=args.frontmatter,
        output=args.output,
        pdf=args.pdf,
        pdf_output=args.pdf_output,
    )
