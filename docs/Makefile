# Build targets for the documentation. Run them inside the docs container;
# docs/README.md has the Docker commands.
SPHINXOPTS ?= -W --keep-going
SOURCEDIR   = .
BUILDDIR    = _build

.PHONY: html linkcheck images clean

html:
	sphinx-build $(SPHINXOPTS) -b html $(SOURCEDIR) $(BUILDDIR)/html

linkcheck:
	sphinx-build -b linkcheck $(SOURCEDIR) $(BUILDDIR)/linkcheck

images:
	python _tools/check_images.py

clean:
	python -c "import shutil; shutil.rmtree('$(BUILDDIR)', ignore_errors=True)"
