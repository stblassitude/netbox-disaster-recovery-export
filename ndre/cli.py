from __future__ import annotations

import sys
from pathlib import Path

import requests
from pynetbox import RequestError

from ndre.client import NetboxClient
from ndre.collect import (
    collect_connections,
    collect_devices,
    collect_dns,
    collect_interfaces,
    collect_other_tagged_objects,
    collect_subnets,
)
from ndre.config import parse_args
from ndre.models import ExportData
from ndre.render_markdown import load_frontmatter, now_iso, render
from ndre.render_pdf import PdfDependencyError, PdfRenderError, render_pdf


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)

    client = NetboxClient(config.netbox_url, config.netbox_token, config.tls_verify)

    try:
        tag_found = client.tag_exists(config.tag)
    except RequestError as exc:
        status = getattr(exc.req, "status_code", None)
        if status in (401, 403):
            print(
                f"error: Netbox rejected the API token ({status} {exc.req.reason}): {exc.error}",
                file=sys.stderr,
            )
        else:
            print(f"error: Netbox request failed: {exc}", file=sys.stderr)
        return 1
    except requests.exceptions.ConnectionError as exc:
        print(f"error: could not connect to Netbox at {config.netbox_url}: {exc}", file=sys.stderr)
        return 1

    if not tag_found:
        print(f"error: no tag '{config.tag}' found in Netbox", file=sys.stderr)
        return 1

    print(f"Fetching devices tagged '{config.tag}'...", file=sys.stderr)
    devices, raw_devices = collect_devices(client, config.tag)

    print("Fetching cabling...", file=sys.stderr)
    connections = collect_connections(client, raw_devices)

    print("Fetching interfaces and IP addresses...", file=sys.stderr)
    interfaces, device_ips = collect_interfaces(client, raw_devices)

    print(f"Fetching VLANs and subnets tagged '{config.tag}'...", file=sys.stderr)
    subnets = collect_subnets(client, config.tag, device_ips)

    all_ip_infos = [ip for section in subnets for ip in section.ip_addresses]
    dns_zones = collect_dns(all_ip_infos)

    print(f"Fetching other objects tagged '{config.tag}'...", file=sys.stderr)
    other_objects = collect_other_tagged_objects(client, config.tag)

    data = ExportData(
        title=config.title,
        generated_at=now_iso(),
        tag=config.tag,
        frontmatter=load_frontmatter(config.frontmatter),
        devices=devices,
        connections=connections,
        interfaces=interfaces,
        subnets=subnets,
        dns_zones=dns_zones,
        other_objects=other_objects,
    )

    markdown = render(data)
    Path(config.output).write_text(markdown, encoding="utf-8")
    print(f"Wrote {config.output}", file=sys.stderr)

    if config.pdf:
        pdf_output = config.pdf_output or str(Path(config.output).with_suffix(".pdf"))
        try:
            render_pdf(config.output, pdf_output)
        except (PdfDependencyError, PdfRenderError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote {pdf_output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
