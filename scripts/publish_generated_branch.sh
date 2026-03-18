#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
POSITIONAL_ARGS=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] <target-branch> [publish-root] [publish-subdir]"
      echo "  --dry-run   Run publish flow without commit/push"
      exit 0
      ;;
    *)
      POSITIONAL_ARGS+=("$1")
      shift
      ;;
  esac
done

TARGET_BRANCH="${POSITIONAL_ARGS[0]:-}"
PUBLISH_ROOT="${POSITIONAL_ARGS[1]:-generated}"
PUBLISH_SUBDIR="${POSITIONAL_ARGS[2]:-generated}"

if [ -z "$TARGET_BRANCH" ]; then
  echo "Usage: $0 [--dry-run] <target-branch> [publish-root] [publish-subdir]" >&2
  exit 1
fi

if [ ! -d "$PUBLISH_ROOT" ]; then
  echo "Publish root does not exist: $PUBLISH_ROOT" >&2
  exit 1
fi

if [ -z "$PUBLISH_SUBDIR" ]; then
  echo "Publish subdir must not be empty" >&2
  exit 1
fi

PUBLISH_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$PUBLISH_DIR"
}
trap cleanup EXIT

cp -a "$PUBLISH_ROOT"/. "$PUBLISH_DIR"/

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if git ls-remote --exit-code --heads origin "$TARGET_BRANCH" >/dev/null 2>&1; then
  git fetch origin "$TARGET_BRANCH"
  git checkout -B "$TARGET_BRANCH" "origin/$TARGET_BRANCH"
else
  git checkout --orphan "$TARGET_BRANCH"
  find . -mindepth 1 -maxdepth 1 ! -name ".git" -exec rm -rf {} +
fi

mkdir -p "$PUBLISH_SUBDIR"

for entry in "$PUBLISH_DIR"/* "$PUBLISH_DIR"/.[!.]* "$PUBLISH_DIR"/..?*; do
  [ -e "$entry" ] || continue
  name="$(basename "$entry")"
  [ "$name" = ".git" ] && continue
  cp -a "$entry" "$PUBLISH_SUBDIR"/
done

# CI-only safeguard: if a previously published artifact becomes empty in this run,
# keep the file path as an empty file to avoid external URL 404.
while IFS= read -r tracked; do
  [ -n "$tracked" ] || continue
  if [[ "$tracked" != "$PUBLISH_SUBDIR/"* ]]; then
    continue
  fi
  case "$tracked" in
    *.list|*.conf|*.yaml|*.json|*.srs) ;;
    *) continue ;;
  esac
  relative="${tracked#$PUBLISH_SUBDIR/}"
  if [ ! -f "$PUBLISH_DIR/$relative" ] && [ -f "$tracked" ]; then
    : > "$tracked"
  fi
done < <(
  git ls-files
)

# Keep generated branch clean from Python cache artifacts.
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
*.pyo
cache/
EOF

# Remove accidentally tracked cache files from previous runs.
git rm -r --cached --ignore-unmatch src/__pycache__ || true
git rm -r --cached --ignore-unmatch cache || true
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
rm -rf cache

git add -A .

if git diff --staged --quiet; then
  echo "No changes to commit."
  exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[DRY-RUN] Changes prepared for branch '$TARGET_BRANCH' from '$PUBLISH_ROOT' into '$PUBLISH_SUBDIR'."
  git diff --cached --name-status
  echo "[DRY-RUN] Skip commit and push."
  exit 0
fi

git commit -m "chore: auto-generate rules"
git push origin HEAD:"$TARGET_BRANCH"
