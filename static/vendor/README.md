# Vendored front-end files

Third-party files the templates load. They are served from this directory so that no page asks another host for anything: a self-hosted install makes no outside request and does not pass visitors' IP addresses to a CDN.

Each file is an unmodified copy taken from the official npm package tarball. Every file was compared with the copy jsDelivr serves for the same version (the address the templates used before) and is byte-identical. Do not edit these files; restyle in `static/css/app.css` instead.

## Bootstrap 5.3.3

- Licence: MIT, see `bootstrap-5.3.3/LICENSE`
- Source: <https://registry.npmjs.org/bootstrap/-/bootstrap-5.3.3.tgz>
- Tarball SHA-256: `38cee936dbd80138de6775683149f22e9226fc2d654392337a921f53000c789e`
- Tarball npm integrity: `sha512-8HLCdWgyoMguSO9o+aH+iuZ+aht+mzW0u3HIMzVu7Srrpv7EBBxTnrFlSCskwdY1+EOFQSm7uMJhNQHkdPcmjg==`

| File here | Path in the tarball | SHA-256 |
| --- | --- | --- |
| `bootstrap-5.3.3/LICENSE` | `package/LICENSE` | `8c14611ae41ac6fd543c13349f22188eb12c69b3e59105c5eca3925a8e4eca3e` |
| `bootstrap-5.3.3/css/bootstrap.min.css` | `package/dist/css/bootstrap.min.css` | `3c8f27e6009ccfd710a905e6dcf12d0ee3c6f2ac7da05b0572d3e0d12e736fc8` |
| `bootstrap-5.3.3/css/bootstrap.min.css.map` | `package/dist/css/bootstrap.min.css.map` | `f12338536350a422c64d02d6e43ff1dea493c3156ad823fe19761cdd5d56c05b` |
| `bootstrap-5.3.3/js/bootstrap.bundle.min.js` | `package/dist/js/bootstrap.bundle.min.js` | `0833b2e9c3a26c258476c46266e6877fc75218625162e0460be9a3a098a61c6c` |
| `bootstrap-5.3.3/js/bootstrap.bundle.min.js.map` | `package/dist/js/bootstrap.bundle.min.js.map` | `5e3e0763164143baaa1ca0706b6100ba0452f911d6ce9713b48e3dbe07b35125` |

## Bootstrap Icons 1.11.3

- Licence: MIT, see `bootstrap-icons-1.11.3/LICENSE`
- Source: <https://registry.npmjs.org/bootstrap-icons/-/bootstrap-icons-1.11.3.tgz>
- Tarball SHA-256: `c68c68dc483cc06c897873d2452e23d33f21865d205edc51349332313bdfdae5`
- Tarball npm integrity: `sha512-+3lpHrCw/it2/7lBL15VR0HEumaBss0+f/Lb6ZvHISn1mlK83jjFpooTLsMWbIjJMDjDjOExMsTxnXSIT4k4ww==`

| File here | Path in the tarball | SHA-256 |
| --- | --- | --- |
| `bootstrap-icons-1.11.3/LICENSE` | `package/LICENSE` | `0fb3e11bd57e896c5a512afd64864d28a37de45d19835016c87ca1ad19ead969` |
| `bootstrap-icons-1.11.3/bootstrap-icons.css` | `package/font/bootstrap-icons.css` | `4ffa6bea4304d2eda418683f56261685ed47bf00995039f27e5ad62d53938d2d` |
| `bootstrap-icons-1.11.3/fonts/bootstrap-icons.woff` | `package/font/fonts/bootstrap-icons.woff` | `bb1de989b83970f6f4e54de1cd974c5cba55b73582da5e1b225a6d0edf029483` |
| `bootstrap-icons-1.11.3/fonts/bootstrap-icons.woff2` | `package/font/fonts/bootstrap-icons.woff2` | `476adf42b40325098fcfa8b36ab3e769186bb4f6ce6a249753e2e1a9c22bf99e` |

## Why the source maps are here

`bootstrap.min.css` and `bootstrap.bundle.min.js` each end with a `sourceMappingURL` comment. The manifest static storage used in production follows those comments during `collectstatic` and stops with an error if the map is missing, so the maps are kept rather than editing the comment out of the files.

The icons stylesheet refers to its fonts as `./fonts/bootstrap-icons.woff2?<hash>`, so the `fonts/` directory has to stay beside it. `collectstatic` rewrites those addresses to the hashed file names.

## Updating

1. Download the new tarball from `https://registry.npmjs.org/<package>/-/<package>-<version>.tgz` and check it against the `dist.integrity` value at `https://registry.npmjs.org/<package>/<version>`.
2. Copy the files listed above into a new `<package>-<version>/` directory here, with the package's `LICENSE`, and delete the old directory.
3. Change the three `{% static 'vendor/...' %}` paths in `templates/base.html` and `templates/base_minimal.html`.
4. Replace the version, source address and SHA-256 values in this file (`shasum -a 256 <file>`).
5. Run `python manage.py collectstatic --noinput` and then `python manage.py test apps.accounts.tests.test_static_assets`. The tests compare every file with the hashes in this file and check that no template or stylesheet loads anything from another host.
