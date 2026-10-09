"""What the app calls itself and how it looks for one organisation.

Templates and emails read a ``Brand`` rather than the Organization directly,
so a request with no organisation (the login page on the main host, a digest
sent without one) still gets a consistent default.
"""
from dataclasses import dataclass

from django.conf import settings

NAVBAR_CLASSES = {
    'dark': 'navbar-dark bg-dark',
    'light': 'navbar-light bg-light border-bottom',
    'primary': 'navbar-dark bg-primary',
}


def _shade(hex_color, factor):
    """Darken a ``#rrggbb`` colour by ``factor`` (0.15 = 15% darker)."""
    value = hex_color.lstrip('#')
    channels = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return '#' + ''.join(f'{max(0, round(c * (1 - factor))):02x}' for c in channels)


@dataclass(frozen=True)
class Brand:
    name: str
    tagline: str = ''
    logo_url: str = ''
    favicon_url: str = ''
    primary_color: str = ''
    navbar_style: str = 'dark'
    support_email: str = ''

    @property
    def navbar_classes(self):
        return NAVBAR_CLASSES.get(self.navbar_style, NAVBAR_CLASSES['dark'])

    @property
    def primary_rgb(self):
        if not self.primary_color:
            return ''
        value = self.primary_color.lstrip('#')
        return ', '.join(str(int(value[i:i + 2], 16)) for i in (0, 2, 4))

    @property
    def primary_hover(self):
        return _shade(self.primary_color, 0.15) if self.primary_color else ''

    @property
    def primary_active(self):
        return _shade(self.primary_color, 0.20) if self.primary_color else ''


def default_brand():
    return Brand(name=settings.DEFAULT_BRAND_NAME, tagline='Open-source EOS framework')


def brand_for(org):
    if org is None:
        return default_brand()
    return Brand(
        name=org.get_display_name(),
        tagline=org.tagline,
        logo_url=org.logo.url if org.logo else '',
        favicon_url=org.favicon.url if org.favicon else '',
        primary_color=org.primary_color,
        navbar_style=org.navbar_style,
        support_email=org.support_email,
    )
