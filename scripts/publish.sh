#!/usr/bin/env bash
#
# Cuts a Betteroff release: picks the version, dates the changelog, runs the
# checks, commits, then tags and pushes.
#
# It doesn't build or upload anything. Pushing the vX.Y.Z tag starts
# .github/workflows/release.yml, which tests, builds, publishes to PyPI (or
# TestPyPI for rc tags) with trusted publishing and creates the GitHub release.
# The tag is the version: hatch-vcs reads it, so no file holds a version number.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

command -v uv >/dev/null 2>&1 || { echo "Error: uv is required. https://docs.astral.sh/uv/" >&2; exit 1; }

confirm() {
  read -r -p "$1 (y/n) " -n 1 -r; echo
  [[ $REPLY =~ ^[Yy]$ ]]
}

echo "Starting the Betteroff release process..."
echo "========================================"

# --- 1. Git state ---
echo "--- Git ---"
BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "main" ]]; then
  echo "Error: on '${BRANCH}'. Release from main." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: uncommitted changes. The release builds from the tagged commit, so commit or stash first." >&2
  git status --short
  exit 1
fi
git fetch --quiet --tags origin main
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  echo "Error: main and origin/main differ. Pull or push first." >&2
  exit 1
fi
echo "On main, clean and up to date."

# --- 2. Version ---
echo "--- Version ---"
LAST_TAG="$(git tag --list 'v*' --sort=-v:refname | grep -Ev '(a|b|rc)[0-9]+$' | head -n 1 || true)"
CURRENT="${LAST_TAG#v}"
if [[ -z "$CURRENT" ]]; then
  echo "No releases yet."
  CURRENT="0.0.0"
  OPTIONS=("first release (0.1.0)" "custom")
else
  echo "Latest release: ${CURRENT}"
  OPTIONS=("patch" "minor" "major" "custom")
fi

bump() {
  python3 - "$CURRENT" "$1" <<'PY'
import sys
major, minor, patch = (int(p) for p in sys.argv[1].split('.'))
kind = sys.argv[2]
if kind == 'patch':
    patch += 1
elif kind == 'minor':
    minor, patch = minor + 1, 0
else:
    major, minor, patch = major + 1, 0, 0
print(f'{major}.{minor}.{patch}')
PY
}

echo "What kind of release?"
select choice in "${OPTIONS[@]}"; do
  case "${choice:-}" in
    patch|minor|major) VERSION="$(bump "$choice")"; break;;
    "first release"*) VERSION="0.1.0"; break;;
    custom) read -r -p "Version (X.Y.Z): " VERSION; break;;
    *) echo "Pick a number from the list.";;
  esac
done

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: '${VERSION}' isn't X.Y.Z." >&2
  exit 1
fi
if git rev-parse -q --verify "refs/tags/v${VERSION}" >/dev/null; then
  echo "Error: v${VERSION} already exists. That version is spent; pick another." >&2
  exit 1
fi

PRERELEASE=false
if confirm "Release candidate on TestPyPI first, instead of the real release?"; then
  N=1
  while git rev-parse -q --verify "refs/tags/v${VERSION}rc${N}" >/dev/null; do N=$((N + 1)); done
  VERSION="${VERSION}rc${N}"
  PRERELEASE=true
fi
TAG="v${VERSION}"
echo "Releasing ${VERSION}"

# --- 3. Changelog ---
# Final releases move [Unreleased] under a dated heading; the workflow reads the
# release notes from that section and refuses a final release without it.
CHANGED=false
if [[ "$PRERELEASE" == false ]]; then
  echo "--- Changelog ---"
  if grep -q "^## \[${VERSION}\]" CHANGELOG.md; then
    echo "CHANGELOG.md already has a [${VERSION}] heading; leaving it."
  else
    TODAY="$(date +%Y-%m-%d)"
    python3 - "$VERSION" "$TODAY" <<'PY'
import pathlib, sys
version, today = sys.argv[1], sys.argv[2]
path = pathlib.Path('CHANGELOG.md')
text = path.read_text()
if '## [Unreleased]\n' not in text:
    sys.exit('Error: CHANGELOG.md needs a "## [Unreleased]" heading.')
path.write_text(text.replace('## [Unreleased]\n', f'## [Unreleased]\n\n## [{version}] - {today}\n', 1))
PY
    CHANGED=true
  fi
  NOTES="$(awk '/^## \['"${VERSION}"'\]/{flag=1; next} /^## /{flag=0} flag' CHANGELOG.md)"
  if [[ -z "$(echo "$NOTES" | tr -d '[:space:]')" ]]; then
    echo "Warning: nothing under [${VERSION}] in CHANGELOG.md; the release notes would be empty."
    confirm "Continue?" || { git checkout -- CHANGELOG.md; echo "Cancelled."; exit 1; }
  else
    echo "Release notes:"
    echo "$NOTES"
  fi
  confirm "Is CHANGELOG.md accurate?" || { git checkout -- CHANGELOG.md; echo "Cancelled."; exit 1; }
  confirm "Are the README and docs current?" || { git checkout -- CHANGELOG.md; echo "Cancelled."; exit 1; }
fi

# --- 4. Checks ---
echo "--- Checks ---"
uv sync --locked --all-extras --quiet
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest -q
rm -rf dist && uv build --quiet && uvx twine check --strict dist/* && rm -rf dist
echo "Checks passed."

# --- 5. Confirm ---
echo "--- Ready ---"
if [[ "$PRERELEASE" == true ]]; then
  echo "This will tag the current commit ${TAG} and push it. The workflow publishes to TestPyPI."
else
  echo "This will commit the changelog, push main, tag ${TAG} and push it."
  echo "The workflow publishes to PyPI and creates the GitHub release."
fi
confirm "Go?" || {
  [[ "$CHANGED" == true ]] && git checkout -- CHANGELOG.md
  echo "Cancelled."
  exit 1
}

# --- 6. Commit, tag, push ---
echo "--- Git ---"
if [[ "$CHANGED" == true ]]; then
  git add CHANGELOG.md
  git commit -m "chore(release): ${TAG}"
  git push origin main
fi
git tag -a "$TAG" -m "Betteroff ${VERSION}"
git push origin "$TAG"
echo "Pushed ${TAG}."

# --- 7. Watch ---
echo "========================================"
if command -v gh >/dev/null 2>&1; then
  echo "Waiting for the release workflow to start..."
  RUN_ID=""
  for _ in $(seq 1 15); do
    RUN_ID="$(gh run list --workflow release.yml --branch "$TAG" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
    [[ -n "$RUN_ID" ]] && break
    sleep 2
  done
  if [[ -n "$RUN_ID" ]]; then
    gh run watch "$RUN_ID" --exit-status || {
      echo "The release workflow failed: gh run view ${RUN_ID} --log-failed" >&2
      exit 1
    }
  else
    echo "Couldn't find the run yet. Check: gh run list --workflow release.yml"
  fi
else
  echo "Install gh to watch the run here: https://github.com/stiles/betteroff/actions"
fi

echo "Done: ${TAG}."
if [[ "$PRERELEASE" == true ]]; then
  echo "Try it:"
  echo "  uvx --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match \\"
  echo "    --from 'betteroff[charts]==${VERSION}' betteroff --version"
else
  echo "Check it: uvx --refresh betteroff@${VERSION} --version"
  echo "Release: https://github.com/stiles/betteroff/releases/tag/${TAG}"
fi
echo "========================================"
