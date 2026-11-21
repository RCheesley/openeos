"""Shared set-up for the accessibility check: one live server, one headless browser.

Run with ``python manage.py test accessibility``. It is not part of
``python manage.py test apps``; see CONTRIBUTING.md.
"""
import os
import unittest

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings, tag

from . import seed

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # requirements-dev.txt is not installed
    sync_playwright = None


# The live test server finds static files by their plain names. The project's
# manifest storage would link to hashed names instead, which that server
# answers with a 404, leaving every page without static/css/app.css.
PLAIN_STATIC_FILES = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@tag('accessibility')
@override_settings(STORAGES=PLAIN_STATIC_FILES)
class BrowserTestCase(StaticLiveServerTestCase):
    """Seeds the demo organisation and opens a page in a headless Chromium."""

    viewport = {'width': 1280, 'height': 800}

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest(
                'Playwright is not installed. Run: pip install -r requirements-dev.txt '
                '&& playwright install --with-deps --only-shell chromium'
            )
        super().setUpClass()
        # Playwright's synchronous API keeps an event loop running on this
        # thread, which Django would otherwise treat as an async context and
        # refuse database access from. The test still runs on a single thread.
        cls._async_unsafe = os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE')
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls._stop_browser)
        # Containers give /dev/shm 64 MB by default, which Chromium outgrows
        # and then crashes; this flag makes it use the temp directory instead.
        # No GPU process is needed for a headless run, and it costs memory.
        cls.browser = cls.playwright.chromium.launch(args=['--disable-dev-shm-usage', '--disable-gpu'])

    @classmethod
    def _stop_browser(cls):
        if getattr(cls, 'browser', None):
            cls.browser.close()
        cls.playwright.stop()
        if cls._async_unsafe is None:
            os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)
        else:
            os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = cls._async_unsafe

    def setUp(self):
        self.ids = seed.seed()
        # Reduced motion stops Bootstrap's fade transitions leaving text
        # half-transparent at the moment the contrast rule measures it.
        self.context = self.browser.new_context(viewport=self.viewport, reduced_motion='reduce')
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()

    def open(self, path):
        """Load a page and fail early if it is not the page that was asked for."""
        response = self.page.goto(self.live_server_url + path, wait_until='load')
        self.assertEqual(response.status, 200, f'{path} returned HTTP {response.status}')
        landed = self.page.evaluate('location.pathname + location.search')
        self.assertEqual(landed, path, f'{path} redirected to {landed}')
        # Colour contrast and focus results mean nothing on an unstyled page.
        # This holds whether the stylesheets come from a CDN or from static/.
        # A stylesheet that answered with an error page still gets a sheet,
        # but an empty one. Rules of a sheet from another host cannot be read.
        missing = self.page.evaluate('''
            [...document.querySelectorAll("link[rel=stylesheet]")].filter(link => {
                if (!link.sheet) return true;
                try { return link.sheet.cssRules.length === 0; } catch (error) { return false; }
            }).map(link => link.href)
        ''')
        self.assertEqual(missing, [], f'{path}: stylesheets did not load, so the page is unstyled')

    def sign_in(self):
        self.open('/accounts/login/')
        self.page.fill('#id_username', seed.USERNAME)
        self.page.fill('#id_password', seed.PASSWORD)
        with self.page.expect_navigation(wait_until='load'):
            self.page.click('button[type=submit]')
        self.assertEqual(self.page.evaluate('location.pathname'), '/', 'Sign-in did not reach the dashboard')
