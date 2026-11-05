"""Domestic freight settlement ownership stored on the shipment snapshot."""

COMPANY_DIRECT = 'company_direct'
SUPPLIER_ADVANCE = 'supplier_advance'
SUPPLIER_BORNE = 'supplier_borne'
SETTLEMENT_MODES = (COMPANY_DIRECT, SUPPLIER_ADVANCE, SUPPLIER_BORNE)


def settlement_mode(shipment):
    """Legacy shipments retain the historical carrier-payable behavior."""
    snapshot = shipment.domestic_terms_snapshot or {}
    mode = snapshot.get('settlement_mode')
    return mode if mode in SETTLEMENT_MODES else COMPANY_DIRECT


def payable_party(shipment):
    """Return (kind, object) for the party owed domestic freight."""
    mode = settlement_mode(shipment)
    if mode == SUPPLIER_ADVANCE:
        return 'supplier', shipment.order.supplier
    if mode == SUPPLIER_BORNE:
        return None, None
    return ('carrier', shipment.domestic_carrier) if shipment.domestic_carrier_id else (None, None)
