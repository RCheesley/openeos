"""Local Sphinx extension for the Empresadence documentation.

It does three small things, all so the docs are as useful to a program
reading them as to a person:

1. Requires a one-line ``description`` in the front matter of every page, and
   publishes it as the page's ``<meta name="description">``.
2. Publishes each page's Markdown source beside its HTML (``how-to/x.html``
   has ``how-to/x.md``), then writes ``llms.txt`` (an index of every page with
   its description) and ``llms-full.txt`` (every page in one Markdown file) at
   the root of the site.
3. Shows screenshots at their intended size. They are captured at twice the
   pixel density so they stay sharp, so each is displayed at half its pixel
   width.

``sphinx-llms-txt`` was considered for the second job. It lists page titles
only, with no descriptions and no sections, so this does it instead.
"""
from html import escape
from pathlib import Path

import imagesize
from docutils import nodes
from sphinx.util import logging

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = '_static/screenshots/'

# How llms.txt groups pages, by the folder they live in.
SECTIONS = {
    '': 'Start here',
    'tutorials': 'Tutorials',
    'how-to': 'How-to guides',
    'reference': 'Reference',
    'explanation': 'Explanation',
    'hosting': 'Hosting',
    'contributing': 'Contributing to the docs',
}


def description_of(env, docname):
    return str(env.metadata.get(docname, {}).get('description', '')).strip()


def require_description(app, env):
    for docname in sorted(env.found_docs):
        if not description_of(env, docname):
            logger.warning(
                'Add a one-line "description" to the front matter.',
                location=docname, type='empresadence', subtype='description',
            )


def add_meta_description(app, pagename, templatename, context, doctree):
    # Descriptions may mark addresses as code; a meta tag is plain text.
    description = description_of(app.env, pagename).replace('`', '')
    if description:
        context['metatags'] = context.get('metatags', '') + (
            f'<meta name="description" content="{escape(description, quote=True)}">\n'
        )


def size_screenshots(app, doctree):
    for image in doctree.findall(nodes.image):
        uri = image.get('uri', '')
        if SCREENSHOT_DIR not in uri or 'width' in image:
            continue
        path = Path(app.srcdir) / SCREENSHOT_DIR / Path(uri).name
        if path.is_file():
            width, _ = imagesize.get(path)
            image['width'] = f'{width // 2}px'


def pages_in_reading_order(env):
    """Every page, in the order the navigation lists them."""
    order, seen = [], set()

    def visit(docname):
        if docname in seen:
            return
        seen.add(docname)
        order.append(docname)
        for child in env.toctree_includes.get(docname, []):
            visit(child)

    visit(env.config.root_doc)
    order.extend(sorted(env.found_docs - seen))
    return order


def strip_front_matter(text):
    if text.startswith('---\n'):
        end = text.find('\n---\n', 4)
        if end != -1:
            return text[end + 5:].lstrip('\n')
    return text


def write_llms_files(app, exception):
    if exception is not None or app.builder.name not in ('html', 'dirhtml'):
        return
    env = app.env
    outdir = Path(app.outdir)
    base = app.config.html_baseurl
    if base and not base.endswith('/'):
        base += '/'

    index = [f'# {app.config.html_title or app.config.project}', '']
    summary = description_of(env, app.config.root_doc)
    if summary:
        index += [f'> {summary}', '']
    index += [
        'Each link below is the Markdown source of one page. '
        f'Every page in one file: {base}llms-full.txt',
        '',
    ]
    full = []
    current_section = None

    for docname in pages_in_reading_order(env):
        source = Path(env.doc2path(docname))
        if source.suffix != '.md':
            continue
        text = source.read_text(encoding='utf-8')
        target = outdir / f'{docname}.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

        folder = docname.split('/')[0] if '/' in docname else ''
        section = SECTIONS.get(folder, folder.replace('-', ' ').capitalize())
        if section != current_section:
            index += ['' if current_section else None, f'## {section}', '']
            current_section = section
        title = env.titles[docname].astext() if docname in env.titles else docname
        description = description_of(env, docname)
        entry = f'- [{title}]({base}{docname}.md)'
        index.append(f'{entry}: {description}' if description else entry)

        full += [
            f'<!-- page: {docname}.md -->',
            f'<!-- description: {description} -->' if description else None,
            '',
            strip_front_matter(text).rstrip(),
            '',
            '',
        ]

    (outdir / 'llms.txt').write_text(
        '\n'.join(line for line in index if line is not None) + '\n', encoding='utf-8'
    )
    (outdir / 'llms-full.txt').write_text(
        '\n'.join(line for line in full if line is not None), encoding='utf-8'
    )
    logger.info('Wrote llms.txt, llms-full.txt and a .md copy of every page.')


def setup(app):
    app.connect('env-updated', require_description)
    app.connect('html-page-context', add_meta_description)
    app.connect('doctree-read', size_screenshots)
    app.connect('build-finished', write_llms_files)
    return {'version': '1.0', 'parallel_read_safe': True, 'parallel_write_safe': True}
