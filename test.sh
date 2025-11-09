#!/usr/bin/env bash

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)

set -eu

build_image() {
	docker build -f ${script_dir}/tests/Dockerfile -t dmenu-extended-test:latest .
	return $?
}

task() {
	echo "${1} ..."
}

error() {
	echo " ✗ - ${1}"
}

success() {
	echo " ✓ - ${1}"
}

usage() {
	cat <<EOF
Usage: $(
		basename "${BASH_SOURCE[0]}"
	) [-h] [-f]

Run dmenu-extended tests

Available options:

-b, --build          Build Docker image (contains linting tools and test environment)
-c, --check-version  Check that the version defined in pyproject.toml is higher than that listed on pypi
-h, --help           Print this help and exit
-l, --lint           Lint code with ruff/shfmt (uses local tools if available, otherwise Docker)
-s, --system         Run system tests in Docker (requires Docker image)

EOF
	exit
}

parse_params() {
	build=0
	check_version=0
	format=0
	system=0
	lint=0
	while :; do
		case "${1-}" in
		-b | --build) build=1 ;;
		-c | --check-version) check_version=1 ;;
		-a | --system) system=1 ;;
		-h | --help) usage ;;
		-l | --lint) lint=1 ;;
		-?*)
			echo "Unknown option: $1"
			exit 1
			;;
		*) break ;;
		esac
		shift
	done
	args=("$@")
	return 0
}

parse_params "$@"

if [ "${check_version}" -eq 1 ]; then
	version=$(grep -E '^version =' ${script_dir}/pyproject.toml | cut -d '"' -f 2)
	pypi_version=$(curl -s https://pypi.org/pypi/dmenu-extended/json | jq -r '.info.version')
	if ${script_dir}/tests/check_version_string.sh "${version}" "${pypi_version}"; then
		success "The version in pyproject.toml (${version}) has been correctly incremented relative to the version on pypi (${pypi_version})"
		exit 0
	else
		error "The version in pyproject.toml (${version}) has not been incremented relative to the current version on pypi (${pypi_version})"
		exit 1
	fi
fi
if [ "${build}" -eq 1 ] || [ "${system}" -eq 1 ]; then
	image_hash="$(docker images -q dmenu-extended-test:latest)"
	if [ "${build}" -eq 1 ] || [ "${image_hash}" = "" ]; then
		if [ "${image_hash}" = "" ]; then
			task "Docker image not found - building"
		fi
		if ! build_image; then
			error "Failed to build the image"
			exit 1
		else
			success "Image built successfully"
		fi
	fi
fi

if [ "${lint}" -eq 1 ]; then
	# Check if we can run locally or need Docker
	local_ruff=false
	local_shfmt=false
	use_docker=false

	if command -v ruff &>/dev/null; then
		local_ruff=true
	fi
	if command -v shfmt &>/dev/null; then
		local_shfmt=true
	fi

	# If either tool is missing locally, check for Docker image
	if [ "$local_ruff" = false ] || [ "$local_shfmt" = false ]; then
		if docker images | grep -q "dmenu-extended-test"; then
			use_docker=true
			echo "  ℹ Using Docker image for linting (some tools not installed locally)"
		else
			echo ""
			echo "  ⚠ Linting tools not found locally:"
			if [ "$local_ruff" = false ]; then
				echo "    - ruff (Python formatter/linter)"
				echo "      Install with: pip install ruff"
			fi
			if [ "$local_shfmt" = false ]; then
				echo "    - shfmt (Shell formatter)"
				echo "      Install with:"
				echo "        Arch:   sudo pacman -S shfmt"
				echo "        Fedora: sudo dnf install shfmt"
				echo "        Ubuntu: sudo apt install shfmt"
				echo "        Snap:   sudo snap install shfmt"
			fi
			echo ""
			echo "  You can either:"
			echo "    1. Install the tools above locally (recommended for development)"
			echo "    2. Build a Docker image with: ./test.sh --build"
			echo "       (The Docker image contains all linting tools)"
			exit 1
		fi
	fi

	# Run Python checks
	task "Checking Python formatting with ruff"
	if [ "$use_docker" = true ]; then
		if ! docker run --rm dmenu-extended-test:latest bash -c "cd dmenu-extended && ruff format --check ./src/dmenu_extended ./tests"; then
			error "Code formatting check failed - run 'ruff format src/ tests/'"
			exit 1
		fi
	else
		if ! ruff format --check ./src/dmenu_extended ./tests; then
			error "Code formatting check failed - run 'ruff format src/ tests/'"
			exit 1
		fi
	fi
	success "Code formatting check passed"

	task "Checking Python style with ruff"
	if [ "$use_docker" = true ]; then
		if ! docker run --rm dmenu-extended-test:latest bash -c "cd dmenu-extended && ruff check ./src/dmenu_extended ./tests"; then
			error "Code style check failed - run 'ruff check --fix src/ tests/'"
			exit 1
		fi
	else
		if ! ruff check ./src/dmenu_extended ./tests; then
			error "Code style check failed - run 'ruff check --fix src/ tests/'"
			exit 1
		fi
	fi
	success "Code style check passed"

	task "Checking shell script formatting with shfmt"
	if [ "$use_docker" = true ]; then
		if ! docker run --rm dmenu-extended-test:latest bash -c "cd dmenu-extended && shfmt -d *.sh"; then
			error "Shell formatting check failed - run 'shfmt -w *.sh'"
			exit 1
		fi
	else
		if ! shfmt -d *.sh; then
			error "Shell formatting check failed - run 'shfmt -w *.sh'"
			exit 1
		fi
	fi
	success "Shell formatting check passed"
fi

if [ "${system}" -eq 1 ]; then
	trap 'docker rmi dmenu-extended-test > /dev/null' EXIT
	docker run --rm dmenu-extended-test:latest bash -c "cd /home/user/dmenu-extended/src/dmenu_extended && python3 -m pytest ../../tests"
	docker run --rm dmenu-extended-test:latest /home/user/dmenu-extended/tests/system_tests.sh
fi

# Fallback for running tests locally without Docker
if [ "${system}" -eq 0 ] && [ "${lint}" -eq 0 ] && [ "${build}" -eq 0 ] && [ "${check_version}" -eq 0 ]; then
	cd ${script_dir}/src/dmenu_extended
	python3 -m pytest ../../tests
fi
