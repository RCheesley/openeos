import hashlib
import posixpath
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.storage import staticfiles_storage
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Membership, Organization

VENDOR = Path(settings.BASE_DIR) / 'static' / 'vendor'
OTHER_HOST = r'(?:[a-z][a-z0-9+.-]*:)?//'
RESOURCE_ATTR = re.compile(
    r'''\b(?P<attr>src|href|srcset|poster)\s*=\s*["']?\s*(?P<url>''' + OTHER_HOST + r'''[^"'\s>]*)''',
    re.IGNORECASE,
)
CSS_URL = re.compile(r'''url\(\s*["']?\s*(?P<url>[^"')\s]+)''', re.IGNORECASE)
CSS_IMPORT = re.compile(r'''@import\s+["'](?P<url>[^"']+)''', re.IGNORECASE)
OPEN_TAG = re.compile(r'<([a-zA-Z][a-zA-Z0-9-]*)')
TAG_ATTR = re.compile(
    r'''<(?P<tag>[a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?\s(?:src|href)\s*=\s*["'](?P<url>[^"']*)["']''',
)
README_ROW = re.compile(r'^\| `(?P<path>[^`]+)` \| `[^`]+` \| `(?P<sha>[0-9a-f]{64})` \|$', re.MULTILINE)


def other_host(url):
    return re.match(OTHER_HOST, url.strip(), re.IGNORECASE) is not None


def outside_requests(text):
    """Addresses on another host that a browser would fetch without being asked.

    Links a person has to click (``<a href>``) are ordinary content and are left alone.
    """
    found = []
    for match in RESOURCE_ATTR.finditer(text):
        tags = OPEN_TAG.findall(text[:match.start()])
        if tags and tags[-1].lower() == 'a':
            continue
        found.append((match.start(), match.group('url')))
    for pattern in (CSS_URL, CSS_IMPORT):
        for match in pattern.finditer(text):
            if other_host(match.group('url')):
                found.append((match.start(), match.group('url')))
    return [(text.count('\n', 0, position) + 1, url) for position, url in sorted(found)]


class OutsideRequestScanTest(SimpleTestCase):
    """Nothing the app serves may pull a script, style, font or image from another host."""

    def test_scanner_tells_a_loaded_resource_from_a_link(self):
        self.assertEqual(
            outside_requests('<p>\n<script src="https://cdn.example/x.js"></script>'),
            [(2, 'https://cdn.example/x.js')],
        )
        self.assertEqual(
            outside_requests('<link rel="stylesheet" href="//cdn.example/x.css">'),
            [(1, '//cdn.example/x.css')],
        )
        self.assertEqual(
            outside_requests('<style>@font-face { src: url("https://fonts.example/a.woff2") }</style>'),
            [(1, 'https://fonts.example/a.woff2')],
        )
        self.assertEqual(outside_requests('<a class="x" href="https://example.org/">docs</a>'), [])
        self.assertEqual(outside_requests('<img src="/media/a.png"><a href="mailto:a@example.org">a</a>'), [])

    def test_no_template_loads_anything_from_another_host(self):
        offenders = []
        for directory in settings.TEMPLATES[0]['DIRS']:
            for path in sorted(Path(directory).rglob('*')):
                if not path.is_file() or path.suffix not in {'.html', '.txt'}:
                    continue
                for number, url in outside_requests(path.read_text()):
                    offenders.append(f'{path.relative_to(directory)}:{number} {url}')
        self.assertEqual(offenders, [])

    def test_no_stylesheet_loads_anything_from_another_host(self):
        offenders = []
        for directory in settings.STATICFILES_DIRS:
            for path in sorted(Path(directory).rglob('*.css')):
                for number, url in outside_requests(path.read_text()):
                    offenders.append(f'{path.relative_to(directory)}:{number} {url}')
        self.assertEqual(offenders, [])


class VendoredFilesTest(SimpleTestCase):
    """The vendored files are the published ones, and production static storage can serve them."""

    def test_every_vendored_file_matches_the_hash_recorded_beside_it(self):
        recorded = dict(README_ROW.findall((VENDOR / 'README.md').read_text()))
        on_disk = {
            path.relative_to(VENDOR).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(VENDOR.rglob('*'))
            if path.is_file() and path.name != 'README.md'
        }
        self.assertTrue(recorded)
        self.assertEqual(on_disk, recorded)

    def test_each_vendored_package_ships_its_licence(self):
        packages = [path for path in sorted(VENDOR.iterdir()) if path.is_dir()]
        self.assertTrue(packages)
        for package in packages:
            with self.subTest(package=package.name):
                self.assertTrue((package / 'LICENSE').is_file())

    def test_collected_icons_stylesheet_points_at_collected_fonts(self):
        source = 'vendor/bootstrap-icons-1.11.3/bootstrap-icons.css'
        stored = staticfiles_storage.stored_name(source)
        self.assertNotEqual(stored, source)
        urls = CSS_URL.findall(Path(staticfiles_storage.path(stored)).read_text())
        self.assertEqual(len(urls), 2)
        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(other_host(url))
                target = posixpath.normpath(posixpath.join(posixpath.dirname(stored), url.split('?')[0]))
                self.assertRegex(target, r'/fonts/bootstrap-icons\.[0-9a-f]{12}\.woff2?$')
                self.assertTrue(staticfiles_storage.exists(target), target)


class RenderedPageAssetsTest(TestCase):
    """What a rendered page loads is local, and each static file it names was collected."""

    def setUp(self):
        org = Organization.objects.create(name='Asset Org')
        self.user = User.objects.create_user(username='assetuser', password='pw')
        Membership.objects.create(user=self.user, organization=org)

    def assertLoadsOnlyCollectedFiles(self, path):
        resp = self.client.get(path)
        self.assertEqual(resp.status_code, 200, path)
        html = resp.content.decode()
        self.assertEqual(outside_requests(html), [], path)
        loaded = [
            match.group('url') for match in TAG_ATTR.finditer(html)
            if match.group('tag').lower() in {'link', 'script', 'img'}
        ]
        static = [url for url in loaded if url.startswith(settings.STATIC_URL)]
        for name in ['bootstrap.min', 'bootstrap-icons', 'bootstrap.bundle.min', 'app']:
            self.assertTrue(any(f'/{name}.' in url for url in static), f'{path} does not load {name}')
        for url in static:
            with self.subTest(path=path, url=url):
                self.assertTrue(staticfiles_storage.exists(url[len(settings.STATIC_URL):]), url)

    def test_sign_in_page(self):
        self.assertLoadsOnlyCollectedFiles('/accounts/login/')

    def test_signed_in_pages(self):
        self.client.force_login(self.user)
        for path in ['/', '/vision/', '/vision/print/']:
            with self.subTest(path=path):
                self.assertLoadsOnlyCollectedFiles(path)
