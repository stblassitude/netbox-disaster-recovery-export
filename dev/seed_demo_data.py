#!/usr/bin/env python3
"""Populate the dev Netbox instance with a small tagged sample topology so
the NDRE exporter has something to export. Safe to re-run (idempotent-ish:
uses get_or_create style lookups).
"""

import os
import sys

import pynetbox

URL = os.environ.get("NETBOX_URL", "http://localhost:8000")
TOKEN = os.environ.get("NETBOX_TOKEN", "0123456789abcdef0123456789abcdef01234567")
TAG = os.environ.get("NDRE_TAG", "ndre")

nb = pynetbox.api(URL, token=TOKEN)


def get_or_create(endpoint, defaults=None, **lookup):
    obj = endpoint.get(**lookup)
    if obj:
        return obj
    payload = dict(lookup)
    payload.update(defaults or {})
    return endpoint.create(payload)


def get_or_create2(endpoint, get_kwargs, create_kwargs):
    obj = endpoint.get(**get_kwargs)
    if obj:
        return obj
    return endpoint.create(create_kwargs)


def main():
    tag = get_or_create(
        nb.extras.tags,
        slug=TAG,
        defaults={"name": TAG, "color": "ff0000"},
    )

    site = get_or_create(nb.dcim.sites, slug="core-dc", defaults={"name": "Core DC", "status": "active"})
    manufacturer = get_or_create(nb.dcim.manufacturers, slug="genericco", defaults={"name": "GenericCo"})
    device_type = get_or_create(
        nb.dcim.device_types,
        slug="generic-router",
        defaults={"model": "Generic Router", "manufacturer": manufacturer.id},
    )
    role = get_or_create(nb.dcim.device_roles, slug="core-router", defaults={"name": "Core Router", "color": "2196f3"})
    rack = get_or_create(nb.dcim.racks, name="Rack 1", site_id=site.id, defaults={"site": site.id, "status": "active"})

    router1 = get_or_create(
        nb.dcim.devices,
        name="router1",
        site_id=site.id,
        defaults={
            "site": site.id,
            "device_type": device_type.id,
            "role": role.id,
            "rack": rack.id,
            "position": 10,
            "face": "front",
            "status": "active",
            "serial": "SN-ROUTER1",
            "asset_tag": "AST-0001",
            "tags": [tag.id],
        },
    )
    router2 = get_or_create(
        nb.dcim.devices,
        name="router2",
        site_id=site.id,
        defaults={
            "site": site.id,
            "device_type": device_type.id,
            "role": role.id,
            "rack": rack.id,
            "position": 11,
            "face": "front",
            "status": "active",
            "serial": "SN-ROUTER2",
            "asset_tag": "AST-0002",
            "tags": [tag.id],
        },
    )

    vlan = get_or_create(
        nb.ipam.vlans,
        vid=100,
        name="core-transit",
        site_id=site.id,
        defaults={"site": site.id, "status": "active", "tags": [tag.id]},
    )
    prefix = get_or_create(
        nb.ipam.prefixes,
        prefix="10.0.0.0/30",
        defaults={"site": site.id, "status": "active", "vlan": vlan.id, "tags": [tag.id]},
    )

    iface1 = get_or_create2(
        nb.dcim.interfaces,
        {"device_id": router1.id, "name": "eth0"},
        {
            "device": router1.id,
            "name": "eth0",
            "type": "1000base-t",
            "enabled": True,
            "description": "Link to router2",
        },
    )
    iface2 = get_or_create2(
        nb.dcim.interfaces,
        {"device_id": router2.id, "name": "eth0"},
        {
            "device": router2.id,
            "name": "eth0",
            "type": "1000base-t",
            "enabled": True,
            "description": "Link to router1",
        },
    )

    ip1 = get_or_create2(
        nb.ipam.ip_addresses,
        {"address": "10.0.0.1/30"},
        {
            "address": "10.0.0.1/30",
            "status": "active",
            "dns_name": "router1.core.example.com",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface1.id,
        },
    )
    ip2 = get_or_create2(
        nb.ipam.ip_addresses,
        {"address": "10.0.0.2/30"},
        {
            "address": "10.0.0.2/30",
            "status": "active",
            "dns_name": "router2.core.example.com",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface2.id,
        },
    )

    router1.primary_ip4 = ip1.id
    router1.save()
    router2.primary_ip4 = ip2.id
    router2.save()

    existing_cables = list(nb.dcim.cables.filter(device_id=router1.id))
    if not existing_cables:
        nb.dcim.cables.create(
            {
                "a_terminations": [{"object_type": "dcim.interface", "object_id": iface1.id}],
                "b_terminations": [{"object_type": "dcim.interface", "object_id": iface2.id}],
                "status": "connected",
                "label": "router1-router2",
            }
        )

    print("Seed complete:")
    print(f"  tag: {tag.name} ({tag.id})")
    print(f"  devices: {router1.name}, {router2.name}")
    print(f"  vlan: {vlan.vid} {vlan.name}")
    print(f"  prefix: {prefix.prefix}")


if __name__ == "__main__":
    sys.exit(main())
