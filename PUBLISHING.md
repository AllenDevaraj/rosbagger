# Publishing rosbagger to PyPI

All seven packages are PyPI-ready: each builds a valid wheel + sdist with
SPDX-licensed, `twine check`-clean metadata. This is the path from the monorepo to
published packages. Nothing here is automated — publishing is a deliberate, manual
step you run when you decide to cut a release.

## 0. Prerequisites

- [uv](https://docs.astral.sh/uv/) installed (the repo already uses it).
- A [PyPI](https://pypi.org/) account, plus a [TestPyPI](https://test.pypi.org/)
  account for dry runs.
- An API token for each index (Account settings → API tokens). Export it:

  ```bash
  export UV_PUBLISH_TOKEN="pypi-..."     # or pass --token to `uv publish`
  ```

## 1. Bump the version (all packages move together)

Every package shares one version and pins siblings as `>=X.Y,<X.(Y+1)`. Keep them
in lockstep: bump `version` in all seven `packages/*/pyproject.toml`, and the
sibling pins too if you cross a minor. Then refresh the lock:

```bash
uv lock
```

## 2. Build every package

```bash
rm -rf dist
for p in packages/*/; do uv build "$p" --out-dir dist; done
```

## 3. Check the artifacts

```bash
uvx twine check dist/*
```

Every wheel and sdist must report `PASSED` before you upload.

## 4. Dry run on TestPyPI (recommended)

Publish to TestPyPI first, then install from it in a clean venv to confirm metadata
and dependency resolution are correct end to end:

```bash
uv publish --publish-url https://test.pypi.org/legacy/ dist/*
```

## 5. Publish to PyPI — core first

`rosbagger-core` is the dependency every other package resolves against. Publish it
first so the others' `rosbagger-core>=0.2,<0.3` requirement can resolve from the
index, then publish the rest:

```bash
uv publish dist/rosbagger_core-*        # 1) the dependency root
uv publish dist/bagq-* dist/rosbagger_record-* dist/rosbagger_replay-* \
           dist/rosbagger_rerun-* dist/rosbagger_gui-* dist/rosbagger_desktop-*
```

(`uv publish dist/*` in one shot also works — each file uploads independently — but
core-first is the safe habit, and it matters if a consumer installs in the window
between uploads.)

## 6. Verify

Install from the real index into a throwaway venv:

```bash
python3 -m venv /tmp/verify && /tmp/verify/bin/pip install bagq
/tmp/verify/bin/bagq --version          # -> bagq 0.2.0
```

## After publishing

Once the packages are on PyPI, the monorepo's **one-transaction install caveat
disappears**: a bare `pip install bagq` resolves `rosbagger-core` from the index,
and `pip install "rosbagger-gui[live]"` pulls the live siblings automatically. At
that point, update README.md / INSTALL.md to lead with the plain `pip install`
recipes.

## Tagging (once you push to GitHub)

The git-based install recipes in INSTALL.md target the `v0.2.0` tag. After you push
the repo:

```bash
git tag -a v0.2.0 -m "rosbagger v0.2.0"
git push origin v0.2.0
```
