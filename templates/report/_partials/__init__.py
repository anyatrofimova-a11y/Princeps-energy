# Princeps report partials package.
#
# This package hosts Python-side helpers for the Jinja partials in the sibling
# HTML files (_provenance.html, _revision.html, _reliance.html, _brand.html,
# _citation_macros.html).
#
# Pack-rewrite bots should register the helpers in `helpers.py` as Jinja
# filters/globals on the Jinja `Environment` they use to render their pack.
# See `docs/paperwork_style_guide.md` for the one-line registration snippet.

from .helpers import (
    regcite_lookup,
    register_jinja_helpers,
    format_prov_entry,
    default_revision_code,
)

__all__ = [
    "regcite_lookup",
    "register_jinja_helpers",
    "format_prov_entry",
    "default_revision_code",
]
