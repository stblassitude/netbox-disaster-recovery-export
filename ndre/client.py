"""Thin wrapper around pynetbox with change-log (last modified by) lookups."""

from __future__ import annotations

import sys
from datetime import datetime

import pynetbox
import urllib3
from pynetbox import RequestError
from pynetbox.core.app import App


def _format_last_updated(value) -> str | None:
    """Format Netbox's ISO 8601 last_updated timestamp as "yyyy-mm-dd hh:mm".

    Falls back to the raw value if it doesn't parse as expected -- still
    better than crashing the whole export over a display nicety.
    """
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


class NetboxClient:
    def __init__(self, url: str, token: str, tls_verify: bool = True):
        self.api = pynetbox.api(url, token=token)
        if not tls_verify:
            self.api.http_session.verify = False
            # --insecure means the user already knows and accepts this; the
            # warning would otherwise fire on every single request.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._content_type_ids: dict[tuple[str, str], int] = {}
        # Where the content-type and changelog endpoints live has moved more
        # than once across Netbox versions, and not always in lockstep: e.g.
        # 4.1 already has object-changes under core but content-types are
        # still (renamed, but) under extras.object-types, while 4.5+ has
        # moved both under core. Rather than hardcode a version cutoff, each
        # is resolved independently by trying candidates in order and
        # caching whichever one actually works.
        self._object_types_endpoint_resolved = None
        self._object_changes_endpoint_resolved = None
        # If none of the candidates work (older/newer Netbox than we know
        # about, or a proxy hiding a path), "changed by" is a nice-to-have,
        # not worth failing the whole export over -- this permanently
        # disables the lookup after the first failure and prints one
        # warning instead of one per object.
        self._changelog_unavailable = False

    # -- generic helpers -----------------------------------------------

    def objects_by_tag(self, endpoint, tag: str):
        """Return a list of records from a pynetbox endpoint filtered by tag."""
        return list(endpoint.filter(tag=tag))

    def tag_exists(self, tag: str) -> bool:
        """Check whether a tag with this slug exists in Netbox.

        Every tag-filtered query below fails with an opaque 400 if the tag
        slug doesn't exist, so callers should check this upfront and fail
        with a clear error message instead.
        """
        return self.api.extras.tags.get(slug=tag) is not None

    def discover_taggable_endpoints(self):
        """Discover every list endpoint that supports filtering by tag.

        Uses the OpenAPI schema rather than hardcoding a model list, so
        callers can look for tagged objects of types this tool has no
        dedicated support for. Restricting to endpoints that declare a
        `tag` filter parameter matters, not just for relevance: most
        models (users, tokens, permissions, the changelog, ...) aren't
        taggable, and Netbox's list endpoints silently ignore an unknown
        filter rather than rejecting it -- querying them with `tag=...`
        would return their entire, unfiltered table. Returns a list of
        (app_label, model_slug, Endpoint) tuples.
        """
        spec = self.api.openapi()
        endpoints = []
        for path, methods in spec.get("paths", {}).items():
            get = methods.get("get")
            if not get or "{id}" in path:
                continue
            params = get.get("parameters", [])
            if not any(isinstance(p, dict) and p.get("name") == "tag" for p in params):
                continue

            parts = [p for p in path.strip("/").split("/") if p]
            if parts and parts[0] == "api":
                parts = parts[1:]
            if len(parts) != 2:
                continue

            app_label, model_slug = parts
            app = getattr(self.api, app_label, None)
            if not isinstance(app, App):
                continue
            endpoints.append((app_label, model_slug, app.endpoint(model_slug)))
        return endpoints

    def _object_types_candidates(self):
        core = getattr(self.api, "core", None)
        candidates = []
        if core is not None:
            candidates.append(core.object_types)
        candidates.append(self.api.extras.object_types)
        candidates.append(self.api.extras.content_types)
        return candidates

    def _object_changes_candidates(self):
        core = getattr(self.api, "core", None)
        candidates = []
        if core is not None:
            candidates.append(core.object_changes)
        candidates.append(self.api.extras.object_changes)
        return candidates

    def _warn_changelog_unavailable(self, exc: RequestError) -> None:
        if self._changelog_unavailable:
            return
        self._changelog_unavailable = True
        print(
            f"warning: Netbox changelog lookup unavailable ({exc}); "
            "'last modified by' will be omitted from the export",
            file=sys.stderr,
        )

    @staticmethod
    def _try_candidates(candidates, call):
        """Call `call(endpoint)` against each candidate in turn, returning
        (result, endpoint) from the first that doesn't raise RequestError.
        Re-raises the last RequestError if every candidate fails.
        """
        last_exc = None
        for endpoint in candidates:
            try:
                return call(endpoint), endpoint
            except RequestError as exc:
                last_exc = exc
        raise last_exc

    def _content_type_id(self, app_label: str, model: str) -> int | None:
        key = (app_label, model)
        if key in self._content_type_ids:
            return self._content_type_ids[key]

        if self._changelog_unavailable:
            return None

        candidates = (
            [self._object_types_endpoint_resolved]
            if self._object_types_endpoint_resolved is not None
            else self._object_types_candidates()
        )
        try:
            ct, endpoint = self._try_candidates(candidates, lambda ep: ep.get(app_label=app_label, model=model))
        except RequestError as exc:
            self._warn_changelog_unavailable(exc)
            return None

        self._object_types_endpoint_resolved = endpoint
        self._content_type_ids[key] = ct.id if ct else None
        return self._content_type_ids[key]

    def last_change(self, obj, app_label: str, model: str) -> tuple[str | None, str | None]:
        """Return (last_updated, changed_by_username) for a Netbox object.

        last_updated comes straight off the object (no extra API call).
        changed_by requires one extra query against the change log (the
        Netbox REST API does not expose "last modified by" directly on
        objects). The caller must supply the object's (app_label, model)
        content-type key explicitly -- deriving it from the object's URL is
        unreliable because plural-to-singular model names aren't regular
        (e.g. "prefixes" -> "prefix", not "prefixe").
        """
        last_updated = _format_last_updated(getattr(obj, "last_updated", None))

        changed_by = None
        ct_id = self._content_type_id(app_label, model)
        if ct_id is not None:
            candidates = (
                [self._object_changes_endpoint_resolved]
                if self._object_changes_endpoint_resolved is not None
                else self._object_changes_candidates()
            )
            try:
                changes, endpoint = self._try_candidates(
                    candidates,
                    lambda ep: list(
                        ep.filter(
                            changed_object_type_id=ct_id,
                            changed_object_id=obj.id,
                            ordering="-time",
                            limit=1,
                        )
                    ),
                )
                self._object_changes_endpoint_resolved = endpoint
            except RequestError as exc:
                self._warn_changelog_unavailable(exc)
                changes = []
            if changes:
                user = changes[0].user
                changed_by = user.display if user else getattr(changes[0], "user_name", None)
        return last_updated, changed_by
