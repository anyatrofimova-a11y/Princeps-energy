"""
Central regulatory-version registry for Princeps.

Import the :mod:`app.regulatory.versions` module (or the convenience helpers
re-exported here) whenever a generated document, pack, or report cites a
standard by issue number / date / URL. This prevents regenerated packs from
quoting a superseded version.

Usage
-----
    from app.regulatory import get, cite, REGULATIONS

    g99 = get("g99")                # full record
    line = cite("g99")              # human-readable one-liner
"""

from .versions import (  # noqa: F401
    REGULATIONS,
    NPPF_PARA_MAP,
    get,
    cite,
    all_keys,
    validate_citation,
)
