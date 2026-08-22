"""Stable category metadata for product-list responses.

The product pages need to style rows by the owning L2 category.  A product may
store an L2 or L3 node, so consumers should not have to reproduce the parent
walk (or infer it from display labels).  This module deliberately only reads
already-loaded relations; list views are responsible for selecting
``category_node`` and ``category_node__parent`` up front.
"""


def category_metadata(category=None, *, spu=None):
    """Return tenant-safe, display-stable category identifiers and labels.

    ``category`` is normally the row's effective ``ProductCategory``.  When a
    legacy row has no direct category, ``spu`` supplies the generated SPU's
    category as a fallback.  If the node is absent, the SPU's persisted L2
    code is retained as a compatibility fallback while IDs/names stay empty.
    This keeps the response deterministic without issuing a query for missing
    relations.
    """

    node = category
    if node is None and spu is not None:
        node = getattr(spu, "category_node", None)

    category_node_id = getattr(node, "id", None)
    l2 = None
    if node is not None:
        level = getattr(node, "level", None)
        if level == 3:
            # List querysets select_related ``category_node__parent``.  The
            # getattr form also works for detail/create responses where the
            # relation is not preloaded, at the cost of one bounded lookup.
            l2 = getattr(node, "parent", None)
        elif level == 2:
            l2 = node

    if l2 is not None:
        l2_id = getattr(l2, "id", None)
        l2_code = getattr(l2, "code", "") or ""
        l2_name = getattr(l2, "name", "") or ""
    else:
        l2_id = None
        l2_code = getattr(spu, "l2_code", "") or "" if spu is not None else ""
        l2_name = ""

    return {
        "category_node_id": category_node_id,
        "category_l2_id": l2_id,
        "category_l2_code": l2_code,
        "category_l2_name": l2_name,
    }


def category_metadata_from_spu(spu):
    """Resolve category metadata from a ProductSPU without changing callers."""

    return category_metadata(getattr(spu, "category_node", None), spu=spu)
