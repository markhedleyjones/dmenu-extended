# Automated Release Setup Guide

This document explains how to configure automated releases with PyPI publishing.

## Overview

The project uses **python-semantic-release** to automatically:
1. Analyze commit messages to determine version bump
2. Update version in `pyproject.toml`
3. Generate/update `CHANGELOG.md`
4. Create git tags
5. Create GitHub releases
6. Publish to PyPI

## Prerequisites

- Repository admin access
- PyPI account with publishing rights to the `dmenu-extended` package

## Setup Instructions

### 1. Create PyPI API Token

1. Log in to [PyPI](https://pypi.org/)
2. Go to Account Settings → API tokens
3. Click "Add API token"
4. Configure the token:
   - **Token name**: `github-actions-dmenu-extended`
   - **Scope**: Select "Project: dmenu-extended" (recommended) or "Entire account" (less secure)
5. Click "Create token"
6. **IMPORTANT**: Copy the token immediately - it won't be shown again!
   - It will look like: `pypi-AgEIcHlwaS5vcmc...` (starts with `pypi-`)

### 2. Add PyPI Token to GitHub Secrets

1. Go to your GitHub repository: `https://github.com/MarkHedleyJones/dmenu-extended`
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Configure the secret:
   - **Name**: `PYPI_API_TOKEN`
   - **Value**: Paste the entire token from PyPI (including the `pypi-` prefix)
5. Click **Add secret**

### 3. Verify GitHub Actions Permissions

1. In your repository, go to **Settings** → **Actions** → **General**
2. Scroll to **Workflow permissions**
3. Ensure the following is selected:
   - ✅ **Read and write permissions**
   - ✅ **Allow GitHub Actions to create and approve pull requests**
4. Click **Save** if you made changes

### 4. Test the Setup

Create a test commit to verify everything works:

```bash
# Make a small change
echo "# Test" >> README.md

# Commit using conventional commit format
git add README.md
git commit -m "docs: test automated release"

# Push to main (or create a PR and merge it)
git push origin main
```

After pushing to `main`, the release workflow will:
1. Run automatically (check the **Actions** tab on GitHub)
2. Determine this is a documentation change (no version bump)
3. If it were a `fix:` or `feat:`, it would:
   - Bump the version
   - Update CHANGELOG.md
   - Create a git tag
   - Create a GitHub release
   - Publish to PyPI

## How Versioning Works

Commits determine the version bump:

| Commit Type | Version Change | Example |
|-------------|----------------|---------|
| `fix:` | Patch (1.3.0 → 1.3.1) | Bug fixes |
| `feat:` | Minor (1.3.0 → 1.4.0) | New features |
| `feat!:` or `BREAKING CHANGE:` | Major (1.3.0 → 2.0.0) | Breaking changes |
| `docs:`, `chore:`, etc. | No change | Documentation, maintenance |

### Examples

```bash
# Patch release (1.3.0 → 1.3.1)
git commit -m "fix: resolve cache corruption issue"

# Minor release (1.3.0 → 1.4.0)
git commit -m "feat: add vim-style keybindings"

# Major release (1.3.0 → 2.0.0)
git commit -m "feat!: redesign configuration API"

# Or with detailed breaking change description:
git commit -m "feat: new plugin system

BREAKING CHANGE: The plugin API has been redesigned.
Old plugins will need to be updated to work with this version."

# No release (docs only)
git commit -m "docs: update installation instructions"
```

## Monitoring Releases

### Check Release Status

1. Go to **Actions** tab in GitHub
2. Look for the "Semantic Release" workflow
3. Click on a run to see details

### Verify PyPI Publication

After a successful release:
1. Visit: https://pypi.org/project/dmenu-extended/
2. Confirm the new version is listed
3. Check the release history

### Verify GitHub Release

1. Go to: https://github.com/MarkHedleyJones/dmenu-extended/releases
2. The new release should appear with:
   - Version tag (e.g., `v1.4.0`)
   - Auto-generated changelog
   - Release assets

## Troubleshooting

### Release workflow fails with "Invalid credentials"

**Problem**: PyPI token is incorrect or expired

**Solution**:
1. Create a new PyPI token (old tokens may have expired)
2. Update the `PYPI_API_TOKEN` secret in GitHub
3. Re-run the failed workflow

### Release workflow fails with "Permission denied"

**Problem**: GitHub Actions doesn't have write permissions

**Solution**:
1. Go to Settings → Actions → General → Workflow permissions
2. Enable "Read and write permissions"
3. Enable "Allow GitHub Actions to create and approve pull requests"

### No release created even with `feat:` or `fix:` commit

**Problem**: Commit message format might be incorrect

**Solution**:
Check your commit message follows this exact format:
```
type: description
```
Common mistakes:
- ❌ `Fix: bug` (type should be lowercase)
- ❌ `fix bug` (missing colon)
- ❌ `fix : bug` (space before colon)
- ✅ `fix: bug` (correct)

### Version bump is wrong (major instead of minor, etc.)

**Problem**: Commit type might not match intent

**Solution**:
- For breaking changes, use `type!:` or include `BREAKING CHANGE:` in body
- For new features, use `feat:`
- For bug fixes, use `fix:`

## Manual Release (Emergency Override)

If automated release fails and you need to publish manually:

```bash
# Manually bump version in pyproject.toml
# Then build and publish:
python -m build
python -m twine upload dist/*
```

**Note**: Avoid manual releases when possible - they bypass changelog generation and git tagging.

## Disabling Automated Releases

To temporarily disable automated releases:
1. Go to `.github/workflows/release.yml`
2. Comment out or delete the workflow file
3. Commit and push

To re-enable, restore the workflow file.

## Questions?

If you encounter issues:
1. Check the GitHub Actions logs for error messages
2. Verify all secrets are correctly configured
3. Ensure commit messages follow conventional commit format
4. Review https://python-semantic-release.readthedocs.io/ for advanced configuration

## Security Notes

- Never commit PyPI tokens to the repository
- Use project-scoped tokens (not account-wide) when possible
- Rotate tokens periodically (every 6-12 months)
- Delete tokens that are no longer needed
- Use repository secrets for all sensitive credentials
