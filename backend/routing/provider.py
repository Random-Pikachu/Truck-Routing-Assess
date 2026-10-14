import logging
from datetime import datetime

import httpx

from routing import ors, tomtom
from routing.checkpoints import Point
from routing.ors import ROUTE_IDS, OrsError, RouteOption

logger = logging.getLogger(__name__)


def getRouteOptions(
    origin: Point, destination: Point, departure: datetime | None = None, loadLb: float = 0.0
) -> list[RouteOption]:
    """TomTom first (real truck alternatives, traffic aware times), ORS when it can't help."""
    if not tomtom.hasApiKey():
        return ors.getRouteOptions(origin, destination)

    try:
        routes = tomtom.getRouteOptions(origin, destination, departure, loadLb)
    except (tomtom.TomTomError, httpx.HTTPError, KeyError, TypeError) as error:
        # the error never has the key in it, the key only lives in the request params
        logger.warning("TomTom routing failed, falling back to ORS: %s", error)
        return ors.getRouteOptions(origin, destination)

    if len(routes) >= len(ROUTE_IDS):
        return routes

    # TomTom found fewer than 3 different roads, the ORS detours may give more
    try:
        fallback = ors.getRouteOptions(origin, destination)
    except (OrsError, httpx.HTTPError) as error:
        logger.warning("ORS fallback failed, keeping %d TomTom routes: %s", len(routes), error)
        return routes
    if len(fallback) > len(routes):
        return fallback
    return routes
