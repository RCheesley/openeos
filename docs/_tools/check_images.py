"""Check that the docs and the screenshots agree.

Fails (exit code 1) if:

- a page uses an image that does not exist
- an image has no alt text
- a screenshot on disk is not used by any page (an orphan)
- a screenshot is missing from the manifest, or the manifest lists a file that is gone
- a screenshot is larger than the size limit

Run it from anywhere; it needs only the Python standard library:

    python docs/_tools/check_images.py
"""
import json
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
SCREENSHOTS = DOCS / '_static' / 'screenshots'
MANIFEST = Path(__file__).resolve().parent / 'screenshots.json'
MAX_BYTES = 200 * 1024
IMAGE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<target>[^)\s]+)\)')
SKIP_DIRS = {'_build', '_tools', '_ext', '.vale'}


def main():
    problems = []
    used = set()
    pages = [
        page for page in DOCS.rglob('*.md')
        if not SKIP_DIRS & set(page.relative_to(DOCS).parts)
    ]
    for page in pages:
        in_code_block = False
        for number, line in enumerate(page.read_text(encoding='utf-8').splitlines(), start=1):
            if line.lstrip().startswith('```'):
                in_code_block = not in_code_block
            if in_code_block:
                continue
            for match in IMAGE.finditer(line):
                where = f'{page.relative_to(DOCS)}:{number}'
                target = match['target']
                if target.startswith(('http://', 'https://')):
                    continue
                path = (page.parent / target).resolve()
                if not path.is_file():
                    problems.append(f'{where}: image not found: {target}')
                    continue
                if not match['alt'].strip():
                    problems.append(f'{where}: image has no alt text: {target}')
                used.add(path)

    on_disk = set(SCREENSHOTS.glob('*.png'))
    for path in sorted(on_disk - used):
        problems.append(f'orphan: {path.relative_to(DOCS)} is not used by any page')
    for path in sorted(on_disk):
        size = path.stat().st_size
        if size > MAX_BYTES:
            problems.append(f'{path.relative_to(DOCS)} is {size // 1024} KB (limit {MAX_BYTES // 1024} KB)')

    listed = {entry['file'] for entry in json.loads(MANIFEST.read_text(encoding='utf-8'))}
    names = {path.name for path in on_disk}
    for name in sorted(names - listed):
        problems.append(f'{name} is not in {MANIFEST.name}')
    for name in sorted(listed - names):
        problems.append(f'{MANIFEST.name} lists {name}, which does not exist')

    total = sum(path.stat().st_size for path in on_disk)
    print(f'{len(pages)} pages, {len(on_disk)} screenshots, {total // 1024} KB in total.')
    if problems:
        print('\n'.join(problems))
        return 1
    print('Every image exists, has alt text, is used and is in the manifest.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
