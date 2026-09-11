"""Pull tagged objects out of Netbox and shape them into the models used by
the Markdown template.
"""

from __future__ import annotations

import ipaddress as ipmod
import re

from pynetbox import RequestError

from ndre.client import NetboxClient
from ndre.models import (
    Connection,
    DeviceInfo,
    DnsZoneSection,
    InterfaceInfo,
    IPAddressInfo,
    Metadata,
    PrefixInfo,
    SubnetSection,
    TaggedObject,
    TaggedObjectSection,
    VlanInfo,
)


_DIGITS_RE = re.compile(r"(\d+)")


def _natural_key(text: str | None):
    """Sort key comparing digit runs numerically and everything else
    case-insensitively as text, so "eth2" < "eth10" < "eth11" instead of
    the lexicographic "eth10" < "eth11" < "eth2".
    """
    text = text or ""
    return [int(part) if part.isdigit() else part.lower() for part in _DIGITS_RE.split(text)]


def _name(obj) -> str | None:
    return getattr(obj, "name", None) if obj else None


def _label(obj) -> str | None:
    return getattr(obj, "label", None) if obj else None


def _meta(client: NetboxClient, obj, app_label: str, model: str) -> Metadata:
    last_updated, changed_by = client.last_change(obj, app_label, model)
    return Metadata(last_updated=last_updated, changed_by=changed_by)


# -- Devices -----------------------------------------------------------


def collect_devices(client: NetboxClient, tag: str) -> list:
    """Return (DeviceInfo list, raw pynetbox device records), sorted by name."""
    raw = sorted(client.objects_by_tag(client.api.dcim.devices, tag), key=lambda d: _natural_key(d.name))
    devices = []
    for d in raw:
        role = getattr(d, "role", None) or getattr(d, "device_role", None)
        device_type = getattr(d, "device_type", None)
        devices.append(
            DeviceInfo(
                name=d.name,
                site=_name(d.site),
                location=_name(d.location),
                rack=_name(d.rack),
                position=str(d.position) if d.position else None,
                face=_label(d.face),
                role=_name(role),
                manufacturer=_name(getattr(device_type, "manufacturer", None)),
                device_type=getattr(device_type, "model", None),
                serial=d.serial or None,
                asset_tag=d.asset_tag or None,
                status=_label(d.status),
                metadata=_meta(client, d, "dcim", "device"),
            )
        )
    return devices, raw


# -- Connectivity --------------------------------------------------------


def _describe_termination(term) -> str:
    obj = getattr(term, "object", None)
    obj_type = getattr(term, "object_type", "") or ""

    if obj is None:
        return getattr(term, "display", "unknown")

    if "circuittermination" in obj_type:
        circuit = getattr(obj, "circuit", None)
        cid = getattr(circuit, "cid", None) if circuit else None
        provider = getattr(circuit, "provider", None) if circuit else None
        provider_name = _name(provider)
        side = getattr(obj, "term_side", None) or getattr(obj, "name", "")
        label = f"Circuit {cid}" if cid else "Circuit"
        if provider_name:
            label += f" ({provider_name})"
        label += f" side {side}"
        return label

    device = getattr(obj, "device", None)
    name = getattr(obj, "name", None)
    if device and name:
        return f"{_name(device)} :: {name}"

    return getattr(obj, "display", None) or str(obj)


def _local_part(term) -> str:
    obj = getattr(term, "object", None)
    name = getattr(obj, "name", None) if obj else None
    return name or getattr(term, "display", "unknown")


def collect_connections(client: NetboxClient, devices: list) -> dict:
    """Return {device_name: [Connection, ...]}."""
    result: dict[str, list[Connection]] = {}
    seen_cable_ids: set[int] = set()

    for device in devices:
        result.setdefault(device.name, [])
        cables = client.api.dcim.cables.filter(device_id=device.id)
        for cable in cables:
            a_terms = list(getattr(cable, "a_terminations", None) or [])
            b_terms = list(getattr(cable, "b_terminations", None) or [])

            def side_has_device(terms):
                for t in terms:
                    obj = getattr(t, "object", None)
                    dev = getattr(obj, "device", None) if obj else None
                    if dev and dev.id == device.id:
                        return True
                return False

            if side_has_device(a_terms):
                local_terms, remote_terms = a_terms, b_terms
            else:
                local_terms, remote_terms = b_terms, a_terms

            local_desc = ", ".join(_local_part(t) for t in local_terms) or "?"
            remote_desc = ", ".join(_describe_termination(t) for t in remote_terms) or "?"

            result[device.name].append(
                Connection(
                    local_device=device.name,
                    local_termination=local_desc,
                    remote_description=remote_desc,
                    cable_status=_label(cable.status),
                    metadata=_meta(client, cable, "dcim", "cable"),
                )
            )
            seen_cable_ids.add(cable.id)

        result[device.name].sort(key=lambda c: _natural_key(c.local_termination))

    return result


# -- Interfaces + IP addresses on tagged devices -------------------------


def collect_interfaces(client: NetboxClient, devices: list):
    """Return ({device_name: [InterfaceInfo, ...]}, [raw ip-address records],
    {vlan ids referenced by interfaces on these devices}).

    A VLAN doesn't have to be independently tagged to belong in the report:
    if a tagged device has an interface using it (untagged or tagged), it's
    in scope too.
    """
    interfaces: dict[str, list[InterfaceInfo]] = {}
    all_ips = []
    referenced_vlan_ids: set[int] = set()

    for device in devices:
        ips_by_iface: dict[int, list] = {}
        for ip in client.api.ipam.ip_addresses.filter(device_id=device.id):
            assigned = getattr(ip, "assigned_object", None)
            if assigned is not None and getattr(ip, "assigned_object_type", "") == "dcim.interface":
                ips_by_iface.setdefault(assigned.id, []).append(ip)
                all_ips.append(ip)

        iface_list = []
        for iface in client.api.dcim.interfaces.filter(device_id=device.id):
            raw_tagged_vlans = getattr(iface, "tagged_vlans", None) or []
            tagged_vlans = sorted(
                (f"{v.vid} ({v.name})" for v in raw_tagged_vlans), key=_natural_key
            )
            untagged = getattr(iface, "untagged_vlan", None)
            iface_ips = ips_by_iface.get(iface.id, [])

            referenced_vlan_ids.update(v.id for v in raw_tagged_vlans)
            if untagged is not None:
                referenced_vlan_ids.add(untagged.id)

            iface_list.append(
                InterfaceInfo(
                    device=device.name,
                    name=iface.name,
                    type=_label(getattr(iface, "type", None)),
                    enabled=bool(iface.enabled),
                    mtu=iface.mtu,
                    mode=_label(getattr(iface, "mode", None)),
                    bridge=_name(getattr(iface, "bridge", None)),
                    untagged_vlan=f"{untagged.vid} ({untagged.name})" if untagged else None,
                    tagged_vlans=tagged_vlans,
                    ip_addresses=sorted((ip.address for ip in iface_ips), key=_natural_key),
                    metadata=_meta(client, iface, "dcim", "interface"),
                )
            )
        iface_list.sort(key=lambda i: _natural_key(i.name))
        interfaces[device.name] = iface_list

    return interfaces, all_ips, referenced_vlan_ids


# -- VLANs and subnets ----------------------------------------------------


def _vlan_info(client: NetboxClient, v) -> VlanInfo:
    return VlanInfo(
        vid=v.vid,
        name=v.name,
        site=_name(getattr(v, "site", None)),
        group=_name(getattr(v, "group", None)),
        status=_label(v.status),
        metadata=_meta(client, v, "ipam", "vlan"),
    )


def _prefix_info(client: NetboxClient, p) -> PrefixInfo:
    return PrefixInfo(
        prefix=p.prefix,
        vrf=_name(getattr(p, "vrf", None)),
        site=_name(getattr(p, "site", None)),
        status=_label(p.status),
        description=p.description or None,
        metadata=_meta(client, p, "ipam", "prefix"),
    )


def collect_subnets(
    client: NetboxClient, tag: str, extra_ips: list, extra_vlan_ids: set | None = None
) -> list:
    """Pair up in-scope VLANs/prefixes and attach relevant IP addresses.

    A VLAN or prefix is in scope either because it's tagged itself, or
    because a tagged device has an interface using it -- an untagged/
    tagged VLAN, or (handled while attaching IPs below) an address within
    it -- even if the VLAN/prefix object carries no tag of its own.
    """
    tagged_vlans = client.objects_by_tag(client.api.ipam.vlans, tag)
    tagged_prefixes = client.objects_by_tag(client.api.ipam.prefixes, tag)

    vlans = list(tagged_vlans)
    vlan_ids_seen = {v.id for v in vlans}
    for vid in extra_vlan_ids or ():
        if vid in vlan_ids_seen:
            continue
        v = client.api.ipam.vlans.get(vid)
        if v is not None:
            vlans.append(v)
            vlan_ids_seen.add(vid)

    sections: list[SubnetSection] = []
    seen_prefix_ids: set[int] = set()
    seen_vlan_ids: set[int] = set()

    for p in tagged_prefixes:
        if p.id in seen_prefix_ids:
            continue
        seen_prefix_ids.add(p.id)
        vlan = getattr(p, "vlan", None)
        vi = None
        if vlan is not None:
            full_vlan = client.api.ipam.vlans.get(vlan.id)
            vi = _vlan_info(client, full_vlan)
            seen_vlan_ids.add(full_vlan.id)
        sections.append(SubnetSection(prefix=_prefix_info(client, p), vlan=vi))

    for v in vlans:
        if v.id in seen_vlan_ids:
            continue
        seen_vlan_ids.add(v.id)
        matching_prefixes = client.api.ipam.prefixes.filter(vlan_id=v.id)
        matched = False
        for p in matching_prefixes:
            if p.id in seen_prefix_ids:
                continue
            seen_prefix_ids.add(p.id)
            sections.append(SubnetSection(prefix=_prefix_info(client, p), vlan=_vlan_info(client, v)))
            matched = True
        if not matched:
            sections.append(SubnetSection(prefix=None, vlan=_vlan_info(client, v)))

    _attach_ip_addresses(client, sections, extra_ips, seen_prefix_ids, seen_vlan_ids)

    for section in sections:
        section.ip_addresses.sort(key=lambda ip: _natural_key(ip.address))
    sections.sort(key=lambda s: _natural_key(s.prefix.prefix if s.prefix else f"VLAN {s.vlan.vid}"))
    return sections


def _attach_ip_addresses(
    client: NetboxClient,
    sections: list,
    extra_ips: list,
    seen_prefix_ids: set,
    seen_vlan_ids: set,
):
    networks = []
    for section in sections:
        if section.prefix is None:
            continue
        try:
            net = ipmod.ip_network(section.prefix.prefix, strict=False)
        except ValueError:
            continue
        networks.append((net, section))

    seen_ip_ids: set[int] = set()
    for ip in extra_ips:
        if ip.id in seen_ip_ids:
            continue
        seen_ip_ids.add(ip.id)
        try:
            addr = ipmod.ip_interface(ip.address).ip
        except ValueError:
            continue

        section = next((s for net, s in networks if addr in net), None)
        if section is None:
            section = _section_for_orphan_ip(
                client, ip.address, sections, networks, seen_prefix_ids, seen_vlan_ids
            )
        if section is not None:
            section.ip_addresses.append(_ip_info(client, ip))


def _section_for_orphan_ip(
    client: NetboxClient,
    ip_address: str,
    sections: list,
    networks: list,
    seen_prefix_ids: set,
    seen_vlan_ids: set,
) -> SubnetSection | None:
    """An IP on a tagged device's interface is in scope even when its
    containing prefix isn't independently tagged -- look the prefix up in
    Netbox and add a section for it.
    """
    candidates = [
        p for p in client.api.ipam.prefixes.filter(contains=ip_address) if p.id not in seen_prefix_ids
    ]
    if not candidates:
        return None

    prefix = max(candidates, key=lambda p: ipmod.ip_network(p.prefix, strict=False).prefixlen)
    seen_prefix_ids.add(prefix.id)

    vlan = getattr(prefix, "vlan", None)
    vi = None
    if vlan is not None and vlan.id not in seen_vlan_ids:
        full_vlan = client.api.ipam.vlans.get(vlan.id)
        if full_vlan is not None:
            vi = _vlan_info(client, full_vlan)
            seen_vlan_ids.add(full_vlan.id)

    section = SubnetSection(prefix=_prefix_info(client, prefix), vlan=vi)
    sections.append(section)
    networks.append((ipmod.ip_network(prefix.prefix, strict=False), section))
    return section


def _ip_info(client: NetboxClient, ip) -> IPAddressInfo:
    assigned = getattr(ip, "assigned_object", None)
    assigned_to = None
    if assigned is not None:
        device = getattr(assigned, "device", None)
        name = getattr(assigned, "name", None)
        if device and name:
            assigned_to = f"{_name(device)} :: {name}"
    return IPAddressInfo(
        address=ip.address,
        dns_name=ip.dns_name or None,
        status=_label(ip.status),
        role=_label(getattr(ip, "role", None)),
        assigned_to=assigned_to,
        description=ip.description or None,
        metadata=_meta(client, ip, "ipam", "ipaddress"),
    )


# -- DNS (derived from IPAddress.dns_name, grouped by inferred zone) ------


def collect_dns(all_ip_infos: list) -> list:
    zones: dict[str, DnsZoneSection] = {}
    for ip in all_ip_infos:
        if not ip.dns_name:
            continue
        labels = ip.dns_name.split(".")
        zone = ".".join(labels[1:]) if len(labels) > 1 else "(no zone)"
        zones.setdefault(zone, DnsZoneSection(zone=zone)).records.append(ip)

    for section in zones.values():
        section.records.sort(key=lambda ip: _natural_key(ip.dns_name))
    return sorted(zones.values(), key=lambda s: _natural_key(s.zone))


# -- Any other tagged object, discovered generically -----------------------

# Object types already covered by a dedicated, curated collector above.
# Excluded here so they aren't also dumped into the generic section.
_HANDLED_ENDPOINTS = {
    ("dcim", "devices"),
    ("dcim", "interfaces"),
    ("dcim", "cables"),
    ("ipam", "vlans"),
    ("ipam", "prefixes"),
    ("ipam", "ip-addresses"),
    # Generic "this object is tagged" join records (Netbox's taggit-backed
    # tag/object relation, exposed under different names across versions).
    # Every object below only has a tag *because* we found it via this
    # tag, so a table just confirming that is redundant by definition --
    # and it duplicates the curated sections above for any object type
    # (device, VLAN, ...) that already has one.
    ("extras", "tagged-objects"),
    ("extras", "tagged-items"),
}

_SKIPPED_PROPERTIES = {"id", "url", "display", "display_url", "name", "label"}


def _humanize(field: str) -> str:
    words = [w for w in field.replace("-", "_").split("_") if w]
    return " ".join(w.capitalize() for w in words)


def _stringify_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        for key in ("display", "label", "name", "value"):
            if value.get(key):
                return str(value[key])
        return ", ".join(f"{k}: {v}" for k, v in value.items()) or None
    if isinstance(value, (list, tuple)):
        parts = [p for p in (_stringify_value(v) for v in value) if p]
        return ", ".join(parts) or None
    return str(value)


def _object_properties(obj) -> dict[str, str]:
    """Flatten a pynetbox record into a display-name -> string-value dict."""
    raw = dict(obj)
    custom_fields = raw.pop("custom_fields", None) or {}
    for key in _SKIPPED_PROPERTIES:
        raw.pop(key, None)

    props = {}
    for key, value in {**raw, **custom_fields}.items():
        text = _stringify_value(value)
        if text is not None:
            props[_humanize(key)] = text
    return props


def collect_other_tagged_objects(client: NetboxClient, tag: str) -> list[TaggedObjectSection]:
    """Find every object of every type carrying `tag` that isn't already
    covered by one of the curated collectors above.
    """
    sections = []
    for app_label, model_slug, endpoint in client.discover_taggable_endpoints():
        if (app_label, model_slug) in _HANDLED_ENDPOINTS:
            continue
        try:
            records = list(endpoint.filter(tag=tag))
        except RequestError:
            continue
        if not records:
            continue

        objects = []
        columns: list[str] = []
        for obj in records:
            props = _object_properties(obj)
            for key in props:
                if key not in columns:
                    columns.append(key)
            objects.append(TaggedObject(name=str(obj), properties=props))
        objects.sort(key=lambda o: _natural_key(o.name))

        sections.append(
            TaggedObjectSection(
                label=f"{app_label.capitalize()} / {_humanize(model_slug)}",
                columns=columns,
                objects=objects,
            )
        )

    sections.sort(key=lambda s: _natural_key(s.label))
    return sections
