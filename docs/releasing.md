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

1. Move the changelog entries from `## Unreleased` into a new `## 0.2.0 (YYYY-MM-DD)` section and merge that to `main`. A final release fails if this section is missing.
2. Start the release one of two ways:
   - **From GitHub:** *Actions > Release > Run workflow* on `main` and enter `0.2.0`. The workflow creates and pushes the `v0.2.0` tag on the current `main` commit, then continues.
   - **From your machine:**
     ```bash
     git switch main && git pull
     git tag -a v0.2.0 -m "Betteroff 0.2.0"
     git push origin v0.2.0
     ```
3. Approve the `pypi` environment if you set up a reviewer.
4. Check the result:
   ```bash
   uvx --refresh betteroff@0.2.0 --version
   ```

## Pre-releases

Tag `v0.2.0rc1` the same way. It publishes to TestPyPI only and the GitHub release is marked as a pre-release. A changelog section isn't required. To try it:

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
