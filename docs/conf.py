"""Sphinx configuration for the Empresadence documentation.

Sources are MyST Markdown. Build with warnings as errors:

    sphinx-build -W --keep-going -b html docs docs/_build/html
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / '_ext'))

project = 'Empresadence'
author = 'Empresadence Contributors'
copyright = 'Empresadence Contributors'
language = 'en'

extensions = [
    'myst_parser',
    'empresadence_docs',
]

# README.md explains how to build these docs; it is for people reading the
# repository, not a page of the site.
exclude_patterns = ['_build', '_tools', '_ext', '.vale', 'README.md', 'Thumbs.db', '.DS_Store']

# ── MyST ─────────────────────────────────────────────────────────────────────
myst_enable_extensions = ['colon_fence', 'deflist']
# Every heading down to level 3 gets an anchor made from its text. Headings
# that other pages link to carry an explicit (name)= target as well, which
# stays the same if the heading is reworded.
myst_heading_anchors = 3

# ── HTML ─────────────────────────────────────────────────────────────────────
html_theme = 'furo'
html_title = 'Empresadence documentation'
# Read the Docs sets this; it lets llms.txt carry absolute links.
html_baseurl = os.environ.get('READTHEDOCS_CANONICAL_URL', '')
# The Markdown source of every page is published beside it (page.md) by the
# local extension, and under _sources/ by Sphinx for the "view source" link.
html_copy_source = True
html_show_sourcelink = True
html_sourcelink_suffix = ''

# ── Checks ───────────────────────────────────────────────────────────────────
nitpicky = True
linkcheck_ignore = [
    # Addresses that only exist on the reader's own machine or as placeholders.
    r'http://localhost[:/].*',
    r'http://127\.0\.0\.1[:/].*',
    r'https?://[a-z.]*example\.com.*',
]
linkcheck_timeout = 20
linkcheck_retries = 2
