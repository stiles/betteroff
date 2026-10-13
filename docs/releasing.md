# Releasing

Versions come from git tags through hatch-vcs: tag `v0.2.0` builds version `0.2.0`. There is no version number to edit in `pyproject.toml`.

| Tag | Publishes to | GitHub release |
| --- | --- | --- |
| `v0.2.0` | [PyPI](https://pypi.org/project/betteroff/) | Release, notes from `CHANGELOG.md` |
| `v0.2.0rc1`, `v0.2.0b1`, `v0.2.0a1` | [TestPyPI](https://test.pypi.org/project/betteroff/) | Pre-release |

The [release workflow](../.github/workflows/release.yml) runs the full test matrix, builds the sdist and wheel, checks that the built version matches the tag, publishes with PyPI trusted publishing (no API tokens) and creates the GitHub release with both files attached.

## One-time setup

Do this before the first release.

1. **PyPI pending publisher.** Sign in at pypi.org, go to *Your account > Publishing > Add a new pending publisher* and enter:
   - PyPI project name: `betteroff`
   - Owner: `stiles`
   - Repository: `betteroff`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

   The first successful publish creates the project and claims the name.
2. **TestPyPI pending publisher.** Same steps at test.pypi.org, with environment name `testpypi`.
3. **GitHub environments.** In the repository's *Settings > Environments*, create `pypi` and `testpypi`. Adding yourself as a required reviewer on `pypi` makes every production publish wait for a click.
4. **Tag protection (optional).** A tag ruleset for `v*` that only maintainers can create keeps anyone else from triggering a release.

## Cutting a release

Add changelog entries under `## [Unreleased]` as you go. Then run:

```bash
./scripts/publish.sh
```

It stops at any answer that isn't yes:

1. Checks you're on `main`, the tree is clean and `main` matches `origin/main`.
2. Asks for the version: patch, minor or major from the latest release tag, or a custom one. The first run offers 0.1.0. It refuses a version whose tag already exists.
3. Asks whether to cut a release candidate first. Yes tags the next free `rcN`, which goes to TestPyPI and skips the changelog step.
4. For a final release, moves `[Unreleased]` under `## [X.Y.Z] - YYYY-MM-DD`, shows the notes and asks you to confirm the changelog and docs.
5. Runs Ruff, mypy, pytest and a build with `twine check`.
6. Commits `chore(release): vX.Y.Z`, pushes `main`, then creates and pushes the annotated tag.
7. Watches the release workflow with `gh`, if it's installed.

The script doesn't build for upload or create the GitHub release; the workflow does both from the tag. Approve the `pypi` environment when the run reaches it, if you set up a reviewer.

### Without the script

- **From GitHub:** move the changelog entries under a dated `## [X.Y.Z]` heading and merge to `main`, then *Actions > Release > Run workflow* on `main` with the version. The workflow tags the current `main` commit and continues.
- **From your machine:** same changelog edit, then `git tag -a vX.Y.Z -m "Betteroff X.Y.Z" && git push origin vX.Y.Z`.

A final release fails if `CHANGELOG.md` has no section for its version.

## Pre-releases

A tag such as `v0.2.0rc1` publishes to TestPyPI only and the GitHub release is marked as a pre-release. A changelog section isn't required. To try it:

```bash
uvx --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match \
  --from 'betteroff[charts]==0.2.0rc1' betteroff --version
```

## If a release fails

- **Tests or build failed:** nothing was published. Fix the problem on `main`, delete the tag (`git push --delete origin v0.2.0 && git tag -d v0.2.0`) and tag again.
- **Publishing failed:** usually a trusted-publisher setting that doesn't match the workflow name or environment. Fix the setting and re-run the failed jobs from the Actions page.
- **Something wrong after publishing:** PyPI never accepts the same version twice. Yank the release on PyPI if needed and release a new patch version.

## Local checks

```bash
uv build                       # dist/betteroff-<version>.tar.gz and .whl
uvx twine check --strict dist/*
```

Between tags, local builds get development versions such as `0.2.1.dev3`.
