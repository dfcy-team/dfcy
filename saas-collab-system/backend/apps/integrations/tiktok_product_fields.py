"""TK category paths are parent-linked, not an assumed leaf category_id."""

from rest_framework.exceptions import ValidationError


def categories(product):
    chain = product.get("category_chains")
    if chain is None or chain == []:
        return {}
    if not isinstance(chain, list) or len(chain) > 50:
        raise ValidationError("TK_PRODUCT_CATEGORY_CHAIN_INVALID")
    children, ids = {}, set()
    for node in chain:
        if not isinstance(node, dict):
            raise ValidationError("TK_PRODUCT_CATEGORY_CHAIN_INVALID")
        identity, parent, name = node.get("id"), node.get("parent_id"), node.get("local_name")
        if (not isinstance(identity, str) or not identity or identity == "0" or identity in ids
                or not isinstance(parent, str) or parent in children
                or not isinstance(name, str) or not name.strip() or len(name.strip()) > 200
                or "is_leaf" in node and type(node["is_leaf"]) is not bool):
            raise ValidationError("TK_PRODUCT_CATEGORY_CHAIN_INVALID")
        ids.add(identity)
        children[parent] = node
    ordered, current = [], "0"
    while current in children:
        node = children[current]
        if node["id"] in {item["id"] for item in ordered}:
            raise ValidationError("TK_PRODUCT_CATEGORY_CHAIN_INVALID")
        ordered.append(node)
        current = node["id"]
    if (len(ordered) != len(chain)
            or any(node.get("is_leaf") is True for node in ordered[:-1])
            or ordered[-1].get("is_leaf") is not True):
        raise ValidationError("TK_PRODUCT_CATEGORY_CHAIN_INVALID")
    return {"category_l" + str(index + 1): ordered[index]["local_name"].strip() if index < len(ordered) else ""
            for index in range(3)}
