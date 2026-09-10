"""Render ExportData into a Markdown document via Jinja2."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ndre.models import ExportData

TEMPLATE_DIR = Path(__file__).parent / "templates"


def load_frontmatter(paths: list[str]) -> list[str]:
    sections = []
    for p in paths:
        text = Path(p).read_text(encoding="utf-8").strip()
        if text:
            sections.append(text)
    return sections


def render(data: ExportData) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(disabled_extensions=(".j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.md.j2")
    return template.render(
        title=data.title,
        generated_at=data.generated_at,
        tag=data.tag,
        frontmatter=data.frontmatter,
        devices=data.devices,
        connections=data.connections,
        interfaces=data.interfaces,
        subnets=data.subnets,
        dns_zones=data.dns_zones,
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
