# Development environment

Brings up a local Netbox instance in Docker so the exporter can be tested
without touching a real Netbox.

```sh
cd dev
docker compose up -d       # first boot runs migrations, takes ~1-2 minutes
```

Netbox will be reachable at http://localhost:8000, with a superuser
`admin` / `admin` and a pre-provisioned API token:

```
0123456789abcdef0123456789abcdef01234567
```

Load a small tagged sample topology (two routers, a cable between them,
interfaces with IPs, a VLAN and a prefix, all tagged `ndre`):

```sh
../.venv/bin/python seed_demo_data.py
```

Then run the exporter against it from the project root (`--pdf` needs the
`pdf` extra: `.venv/bin/pip install -e ".[pdf]"`):

```sh
.venv/bin/ndre \
  --netbox-url http://localhost:8000 \
  --netbox-token 0123456789abcdef0123456789abcdef01234567 \
  --tag ndre \
  -o /tmp/ndre-export.md \
  --pdf
```

Tear down when done:

```sh
docker compose down          # keep the volumes for next time
docker compose down -v       # or wipe the database too
```
