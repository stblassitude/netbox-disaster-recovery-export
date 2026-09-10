# Netbox Disaster Recovery Export

This Python program exports key data from Netbox that can be stored offline or printed out, to allow the configuration of core network components to be re-created from scratch. The goal is to get the core network back up and running so the VM cluster can start running core services again, including DHCP and Netbox itself. From there, the wider network can be reconfigured, hopefully from backups or automation that pushed Netbox config into switches, etc.

## Frontmatter

NDRE will optionally include one or more sections from a file specified through `--frontmatter`. This allows you to give additional context and information to be part of the document.

## Table of Contents

The document opens with a table of contents linking to each top-level section, both in the Markdown (works on GitHub, VS Code, etc.) and as clickable links plus a bookmark outline in the PDF.

## Netbox objects to document

NDRE exports Netbox data that is relevant to a Disaster Recovery operation; it leaves out information that is not immediately necessary. It also only exports information from a subset of Netbox objects, to keep the size managable.

### Tagging Objects

The selection of objects is accomplished through tags: in general, an objected tagged "NDRE" will be included in the exported document.

### Metadata

For all information exported, the last modified date and the username doing the modification are listed.

### Devices

Devices have their physical properties (location, rack) exported.

### Device Connectivity

An important part of disaster recovery is restoring the physical connections between devices (for example, if a router blows up and has to be swapped out).

NDRE exports all connections (cables) between devices tagged, with a section per device. If two tagged devices have cables between them, these are listed for both devices. Connections include circuits and other relevant object types.

### Device Interfaces

All tagged devices have their interfaces included in the document, including the interface IP addresses, VLAN assignments, bridge settings, etc.

### VLAN and IP subnets

All VLANs and subnets tagged are exported; it is enough to have either the VLAN or the subnet tagged to have both included in the export. A VLAN or subnet used by an interface on a tagged device is also included, even if it carries no tag of its own.

### IP addresses

Any IP address exported through device interfaces or similar is listed in a section per subnet for reference, including its DNS info.

### DNS Entries

Any DNS name (indirectly) tagged is listed, with a section per zone. 

### Other Tagged Objects

Any tagged object of a type not covered by one of the sections above (for
example a tagged circuit, contact, or tenant) is included in an "Other
Tagged Objects" section, grouped by object type. Types with 7 or fewer
properties are listed as one table, one row per object; types with more
properties get a sub-section per object instead, with a table listing each
property and its value.

### PDF rendering

Pass `--pdf` to also render the Markdown export to PDF. This converts the
Markdown to HTML and renders it with [WeasyPrint](https://weasyprint.org/)
using a built-in stylesheet (A4 landscape, small-font tables that wrap
instead of overflowing). Requires the `pdf` extra, which pulls in WeasyPrint
and its native dependencies (Pango/Cairo — on macOS: `brew install pango`).

## Installation

```sh
python3 -m venv .venv
.venv/bin/pip install -e .          # Markdown export only
.venv/bin/pip install -e ".[pdf]"   # also enables --pdf
```

## Usage

```sh
ndre \
  --netbox-url https://netbox.example.com \
  --netbox-token <api-token> \
  --tag ndre \
  --frontmatter intro.md --frontmatter procedures.md \
  -o dr-export.md \
  --pdf
```

`--netbox-url` and `--netbox-token` can also be set via the `NETBOX_URL` and
`NETBOX_TOKEN` environment variables. Run `ndre --help` for the full list of
options.

### DNS Entries in practice

Netbox core has no DNS zone/record objects, so the DNS Entries section is
derived from the `dns_name` field of exported IP addresses; entries are
grouped under an inferred "zone" (everything after the first label of the
DNS name, e.g. `router1.core.example.com` groups under `core.example.com`).

## Development

Use the included Docker Compose setup in [`dev/`](dev/) to bring up a Netbox instance with sample objects to test the export — see [`dev/README.md`](dev/README.md).
