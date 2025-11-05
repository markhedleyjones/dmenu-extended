# Contributing to dmenu-extended

Thank you for considering contributing to dmenu-extended! This document outlines the process and guidelines for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Pull Request Process](#pull-request-process)
- [Code Style](#code-style)
- [Testing](#testing)

## Code of Conduct

We expect all contributors to be respectful and professional. Please be kind and courteous in all interactions.

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/MarkHedleyJones/dmenu-extended.git
   cd dmenu-extended
   ```

2. Install development dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install the package in editable mode:
   ```bash
   pip install -e .
   ```

4. Run tests to ensure everything is working:
   ```bash
   ./test.sh
   ```

## Commit Message Guidelines

**This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated versioning and changelog generation.**

### Commit Message Format

Each commit message consists of a **type**, an optional **scope**, and a **subject**:

```
<type>[optional scope]: <subject>

[optional body]

[optional footer(s)]
```

### Types

The commit type determines how the version will be bumped:

- **fix:** A bug fix (triggers a **PATCH** version bump: 1.3.0 → 1.3.1)
- **feat:** A new feature (triggers a **MINOR** version bump: 1.3.0 → 1.4.0)
- **docs:** Documentation only changes (no version bump)
- **style:** Code style changes (formatting, missing semi-colons, etc.) (no version bump)
- **refactor:** Code refactoring without changing functionality (no version bump)
- **perf:** Performance improvements (triggers a **PATCH** version bump)
- **test:** Adding or updating tests (no version bump)
- **build:** Changes to build system or dependencies (no version bump)
- **ci:** Changes to CI configuration (no version bump)
- **chore:** Other changes that don't modify src or test files (no version bump)

### Breaking Changes

To trigger a **MAJOR** version bump (1.3.0 → 2.0.0), use one of these methods:

1. Add `!` after the type:
   ```
   feat!: remove Python 3.7 support
   ```

2. Add `BREAKING CHANGE:` in the commit body or footer:
   ```
   feat: redesign configuration system

   BREAKING CHANGE: Configuration file format has changed from JSON to YAML.
   Users must migrate their existing config files.
   ```

### Examples

Good commit messages:

```bash
# Bug fix (patch version bump)
fix: correct cache file path on Windows

# New feature (minor version bump)
feat: add support for custom keybindings

# Performance improvement (patch version bump)
perf: optimize file scanning for large directories

# Documentation (no version bump)
docs: update installation instructions for Arch Linux

# Breaking change (major version bump)
feat!: replace JSON config with YAML format

# Breaking change with details (major version bump)
refactor: redesign plugin API

BREAKING CHANGE: Plugin API has been completely redesigned.
Plugins using the old API will need to be updated. See migration
guide at docs/plugin-migration.md
```

Bad commit messages:

```bash
# ❌ Too vague
fix: bug fix

# ❌ Missing type
updated readme

# ❌ Wrong capitalization (should be lowercase)
Fix: Corrected cache bug

# ❌ Missing colon after type
fix corrected cache bug
```

## Pull Request Process

1. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the commit message guidelines above

3. **Ensure tests pass**:
   ```bash
   ./test.sh --build
   ./test.sh --lint
   ./test.sh --system
   ```

4. **Push your branch** and create a Pull Request:
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Do NOT manually update the version number** in `pyproject.toml`
   - Version bumps are handled automatically by semantic-release
   - The version will be updated when your PR is merged to `main`

6. **Wait for CI checks** to pass:
   - Linting (flake8 + Black)
   - System tests
   - Docker build

7. **Address review feedback** if any

8. Once approved and merged, the release workflow will:
   - Analyze your commits
   - Determine the version bump
   - Update `pyproject.toml`
   - Generate/update `CHANGELOG.md`
   - Create a git tag
   - Publish to PyPI

## Code Style

This project uses:
- **Black** for code formatting (max line length: 88)
- **flake8** for linting

Before committing, run:
```bash
./test.sh --lint
```

To auto-format your code:
```bash
black ./src/dmenu_extended
```

## Testing

### Run all tests:
```bash
./test.sh --build --lint --system
```

### Run specific test types:

```bash
# Linting only
./test.sh --lint

# System tests only (requires Docker)
./test.sh --build
./test.sh --system

# Unit tests only (no Docker required)
cd src/dmenu_extended
python3 -m pytest ../../tests
```

### Writing Tests

- Place test files in the `tests/` directory
- Name test files `test_*.py`
- Use pytest for unit tests
- Ensure all tests pass before submitting PR

## Questions?

If you have questions or need help:
- Open an issue with the `question` label
- Check existing issues and discussions
- Review the [README](README.md) for usage information

Thank you for contributing! 🎉
