#!/usr/bin/env bash

set -eu

usage() {
	cat <<EOF
Usage: $(
		basename "${BASH_SOURCE[0]}"
	) [-h] [-f] CHECK_VERSION_STRING REFERENCE_VERSION_STRING

Check a given symantic version string string has been incremented relative to a
reference version string.

Available options:

-h, --help   Print this help and exit
-e, --equal  Accept equal versions
EOF
	exit
}

parse_params() {
	equal=0
	while :; do
		case "${1-}" in
		-h | --help) usage ;;
		-e | --equal) equal=1 ;;
		-?*)
			echo "Unknown option: $1"
			exit 1
			;;
		*) break ;;
		esac
		shift
	done
	args=("$@")

	if [ "${#args[@]}" -ne 2 ]; then
		echo "Invalid number of arguments"
		usage
	fi
	return 0
}

parse_params "$@"

here="$1"
there="$2"

if [ "${equal}" -eq 1 ]; then
	echo "Checking ${here} >= ${there} ..."
else
	echo "Checking ${here} > ${there} ..."
fi
part_names=("placeholder" "major" "minor" "patch")
incremented=0
for part in 1 2 3; do
	this_version_part=$(echo "${here}" | cut -d '.' -f ${part})
	pypi_version_part=$(echo "${there}" | cut -d '.' -f ${part})
	if [ ${incremented} -gt 0 ]; then
		if [ "${this_version_part}" -ne 0 ]; then
			echo " ✗ - After incrementing the ${part_names[${incremented}]} version the ${part_names[${part}]} version should be reset to 0"
			exit 1
		fi
	else
		# No parts of the version string have been incremented yet
		diff=$((${this_version_part} - ${pypi_version_part}))
		if [ ${diff} -eq 1 ]; then
			incremented=${part}
		elif [ ${diff} -gt 1 ]; then
			echo " ✗ - The ${part_names[${part}]} version has been incremented by ${diff}, but should only be incremented by 1"
			exit 1
		elif [ ${diff} -lt 0 ]; then
			echo " ✗ - The ${part_names[${part}]} version has been decremented (from ${pypi_version_part} to ${this_version_part}) but should only be incremented by 1"
			exit 1
		fi
	fi
done

if [ ${incremented} -eq 0 ]; then
	if [ ${equal} -eq 1 ]; then
		echo " ✓ - The version strings are equal"
	else
		echo " ✗ - The version has not been incremented"
		exit 1
	fi
else
	echo " ✓ - The ${part_names[${incremented}]} version component was incremented"
fi
exit 0
