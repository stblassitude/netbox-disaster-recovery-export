"""Thin wrapper around pynetbox with change-log (last modified by) lookups."""

from __future__ import annotations

import pynetbox
from pynetbox import RequestError


class NetboxClient:
    def __init__(self, url: str, token: str, tls_verify: bool = True):
        self.api = pynetbox.api(url, token=token)
        if not tls_verify:
            self.api.http_session.verify = False
        self._content_type_ids: dict[tuple[str, str], int] = {}
        # Netbox >= 4.0 renamed extras.content-types to extras.object-types
        # and moved the changelog from extras.object-changes to
        # core.object-changes. Detected lazily since pynetbox happily hands
        # out an Endpoint object for either name regardless of whether it
        # exists on the server; only an actual request reveals that.
        self._use_legacy_endpoints: bool | None = None

    # -- generic helpers -----------------------------------------------

    def objects_by_tag(self, endpoint, tag: str):
        """Return a list of records from a pynetbox endpoint filtered by tag."""
        return list(endpoint.filter(tag=tag))

    def _object_types_endpoint(self):
        if self._use_legacy_endpoints:
            return self.api.extras.content_types
        return self.api.extras.object_types

    def _object_changes_endpoint(self):
        if self._use_legacy_endpoints:
            return self.api.extras.object_changes
        core = getattr(self.api, "core", None)
        return core.object_changes if core is not None else self.api.extras.object_changes

    def _content_type_id(self, app_label: str, model: str) -> int | None:
        key = (app_label, model)
        if key in self._content_type_ids:
            return self._content_type_ids[key]

        if self._use_legacy_endpoints is None:
            try:
                ct = self._object_types_endpoint().get(app_label=app_label, model=model)
                self._use_legacy_endpoints = False
            except RequestError:
                self._use_legacy_endpoints = True
                ct = self._object_types_endpoint().get(app_label=app_label, model=model)
        else:
            ct = self._object_types_endpoint().get(app_label=app_label, model=model)

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
        last_updated = getattr(obj, "last_updated", None)
        last_updated = str(last_updated) if last_updated else None

        changed_by = None
        ct_id = self._content_type_id(app_label, model)
        if ct_id is not None:
            changes = list(
                self._object_changes_endpoint().filter(
                    changed_object_type_id=ct_id,
                    changed_object_id=obj.id,
                    ordering="-time",
                    limit=1,
                )
            )
            if changes:
                user = changes[0].user
                changed_by = user.display if user else getattr(changes[0], "user_name", None)
        return last_updated, changed_by
