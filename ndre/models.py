"""Plain data structures handed to the Markdown template."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Metadata:
    last_updated: str | None = None
    changed_by: str | None = None

    @property
    def formatted(self) -> str:
        """Renders as "yyyy-mm-dd hh:mm username", degrading gracefully
        if either part is missing."""
        if not self.last_updated:
            return "unknown"
        if self.changed_by:
            return f"{self.last_updated} {self.changed_by}"
        return self.last_updated


@dataclass
class DeviceInfo:
    name: str
    site: str | None
    location: str | None
    rack: str | None
    position: str | None
    face: str | None
    role: str | None
    manufacturer: str | None
    device_type: str | None
    serial: str | None
    asset_tag: str | None
    status: str | None
    metadata: Metadata


@dataclass
class Connection:
    local_device: str
    local_termination: str
    remote_description: str
    cable_status: str | None
    metadata: Metadata


@dataclass
class InterfaceInfo:
    device: str
    name: str
    type: str | None
    enabled: bool
    mtu: int | None
    mode: str | None
    bridge: str | None
    untagged_vlan: str | None
    tagged_vlans: list[str]
    ip_addresses: list[str]
    metadata: Metadata


@dataclass
class VlanInfo:
    vid: int
    name: str
    site: str | None
    group: str | None
    status: str | None
    metadata: Metadata


@dataclass
class PrefixInfo:
    prefix: str
    vrf: str | None
    site: str | None
    status: str | None
    description: str | None
    metadata: Metadata


@dataclass
class SubnetSection:
    prefix: PrefixInfo | None
    vlan: VlanInfo | None
    ip_addresses: list["IPAddressInfo"] = field(default_factory=list)


@dataclass
class IPAddressInfo:
    address: str
    dns_name: str | None
    status: str | None
    role: str | None
    assigned_to: str | None
    description: str | None
    metadata: Metadata


@dataclass
class DnsZoneSection:
    zone: str
    records: list[IPAddressInfo] = field(default_factory=list)


@dataclass
class TaggedObject:
    name: str
    properties: dict[str, str]


@dataclass
class TaggedObjectSection:
    label: str
    columns: list[str]
    objects: list[TaggedObject]


@dataclass
class ExportData:
    title: str
    generated_at: str
    tag: str
    frontmatter: list[str]
    devices: list[DeviceInfo]
    connections: dict[str, list[Connection]]
    interfaces: dict[str, list[InterfaceInfo]]
    subnets: list[SubnetSection]
    dns_zones: list[DnsZoneSection]
    other_objects: list[TaggedObjectSection]
