"""Work out which client address a request came from.

``X-Forwarded-For`` is only believed when a reverse proxy is trusted, and then
only the entries the trusted proxies added themselves. The bundled Nginx
appends the address it saw to whatever the client sent, so the trustworthy
entry is counted from the right, never the first one.
"""
import ipaddress

from django.conf import settings


def trusted_proxy_count():
    """How many reverse proxies in front of Django append to X-Forwarded-For.

    ``TRUSTED_PROXY_COUNT`` wins when set. Otherwise one proxy is assumed
    exactly when ``SECURE_PROXY_SSL_HEADER`` is set (as the production settings
    do for the bundled Nginx), and none when it is not.
    """
    count = getattr(settings, 'TRUSTED_PROXY_COUNT', None)
    if count is None:
        return 1 if getattr(settings, 'SECURE_PROXY_SSL_HEADER', None) else 0
    return max(0, count)


def _parse(raw):
    try:
        address = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    return getattr(address, 'ipv4_mapped', None) or address


def client_address(request):
    """The client's IP address as a string, or None when it cannot be determined."""
    if request is None:
        return None
    address = None
    proxies = trusted_proxy_count()
    if proxies:
        hops = [h for h in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if h.strip()]
        if hops:
            # With fewer entries than proxies the chain is shorter than configured;
            # the left-most entry is then the furthest hop we know about.
            address = _parse(hops[-proxies] if len(hops) >= proxies else hops[0])
    if address is None:
        address = _parse(request.META.get('REMOTE_ADDR', ''))
    return str(address) if address else None


def address_bucket(request):
    """The value limits are counted against: the address, or its /64 for IPv6.

    One IPv6 customer usually holds a whole /64, so counting single addresses
    would let them step around a limit.
    """
    raw = client_address(request)
    if raw is None:
        return None
    address = ipaddress.ip_address(raw)
    if address.version == 6:
        return str(ipaddress.ip_network(f'{address}/64', strict=False))
    return raw
