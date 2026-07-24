"""Country allowlist.

Enforced in the application rather than at an edge, because the public
entrance is an openresty proxy with no GeoIP module rather than a CDN. Traffic
therefore reaches the machine before being rejected; the trade is autonomy,
since no other administrator has to install or maintain anything.

This is noise reduction, not a perimeter. Anyone with a VPS in either country
walks through it, and GeoIP misclassifies roaming users. It is worth having
because the overwhelming majority of unsolicited traffic is broad automated
scanning, and removing that is what makes a real anomaly visible in the log.
See docs/architecture/security.md section 4.1.
"""

from __future__ import annotations

import logging
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path

import geoip2.database
import geoip2.errors

from app.domain.exceptions import CountryNotAllowedError
from app.infrastructure.config import Settings

logger = logging.getLogger(__name__)


class GeoFilter:
    def __init__(self, allowed: frozenset[str], database_path: Path) -> None:
        self._allowed = allowed
        self._reader = geoip2.database.Reader(str(database_path))

    def assert_allowed(self, client_ip: IPv4Address | IPv6Address) -> None:
        try:
            country = self._reader.country(str(client_ip)).country.iso_code
        except geoip2.errors.AddressNotFoundError:
            # Private and unrouted addresses land here. Rejecting them would
            # break the health probes and anything reaching the service over
            # the tailnet, neither of which this filter is aimed at.
            return

        if country not in self._allowed:
            # The country is logged, not returned: telling a caller which rule
            # rejected them is free reconnaissance.
            logger.info("rejected request from %s (%s)", client_ip, country)
            raise CountryNotAllowedError(detail=f"country={country} ip={client_ip}")

    def close(self) -> None:
        self._reader.close()


class NoGeoFilter:
    """Used in development, where there is no database to read."""

    def assert_allowed(self, client_ip: IPv4Address | IPv6Address) -> None:
        return

    def close(self) -> None:
        return


def build_geo_filter(settings: Settings) -> GeoFilter | NoGeoFilter:
    """Fail fast in production if the database is missing.

    Starting without it would silently disable a control that section 13 lists
    as required before public exposure, and nothing downstream would notice.
    """
    path = Path(settings.geoip_db_path)

    if not settings.allowed_country_set:
        return NoGeoFilter()

    if not path.is_file():
        if settings.is_production:
            raise RuntimeError(
                f"ALLOWED_COUNTRIES is set but no GeoLite2 database exists at {path}. "
                "Refusing to start rather than silently serving every country."
            )
        logger.warning("no GeoLite2 database at %s; country filtering is off", path)
        return NoGeoFilter()

    return GeoFilter(settings.allowed_country_set, path)
