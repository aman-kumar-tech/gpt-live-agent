from sqlalchemy.ext.asyncio import AsyncSession

from receptionist.db.models import LabInfo

DEFAULT_HOME_COLLECTION_FEE = 0
DEFAULT_HOME_COLLECTION_WAIVER = None
DEFAULT_BOOKING_LEAD_TIME_HOURS = 0


async def get_lab_info(session: AsyncSession) -> LabInfo | None:
    return await session.get(LabInfo, 1)


async def get_home_collection_fee(session: AsyncSession, order_subtotal) -> float:
    """home_collection_charges.standard_fee_inr, waived once the order
    subtotal reaches waived_if_order_above_inr. Falls back to no fee if
    lab_info/operational_rules isn't configured."""
    lab = await get_lab_info(session)
    rules = (lab.operational_rules if lab else {}) or {}
    charges = rules.get("home_collection_charges") or {}
    fee = charges.get("standard_fee_inr", DEFAULT_HOME_COLLECTION_FEE)
    waiver = charges.get("waived_if_order_above_inr", DEFAULT_HOME_COLLECTION_WAIVER)
    if waiver is not None and order_subtotal >= waiver:
        return 0
    return fee


async def get_booking_lead_time_hours(session: AsyncSession) -> float:
    lab = await get_lab_info(session)
    rules = (lab.operational_rules if lab else {}) or {}
    return rules.get("booking_lead_time_hours", DEFAULT_BOOKING_LEAD_TIME_HOURS)
