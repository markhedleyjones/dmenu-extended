#!/usr/bin/env bash

failed_tests=()
current_test=""

start_test() {
	current_test="$1"
	echo ""
	echo "Running test: $1 ..."
	if [ -f /tmp/output ]; then
		rm /tmp/output
	fi
}

pass() {
	echo " ✓ ${current_test} passed"
}

fail() {
	echo " ✗ ${current_test} failed"
	failed_tests+=("${current_test}")
	if [ -f /tmp/output ]; then
		cat /tmp/output
	fi
}

## TEST DEFINITIONS ##

start_test "dmenu_extended_cache_build"
if dmenu_extended_cache_build >/tmp/output; then pass; else fail; fi

start_test "Check dmenu-extended folder in ~/.cache"
if [ -d ~/.cache/dmenu-extended ]; then pass; else fail; fi

target="/home/user/dmenu-extended/"
start_test "Check the folder: dmenu-extended was added to the cache"
if cat ~/.cache/dmenu-extended/dmenuExtended_folders.txt | grep ${target} >/dev/null; then pass; else fail; fi

target="/home/user/dmenu-extended/src/dmenu_extended/main.py"
start_test "Check the file: main.py was added to the cache"
if cat ~/.cache/dmenu-extended/dmenuExtended_files.txt | grep ${target} >/dev/null; then pass; else fail; fi

## TEST SUMMARY ##

echo ""
if [ ${#failed_tests[@]} -eq 0 ]; then
	echo "All tests passed"
	exit 0
else
	echo "Failed tests:"
	for test in "${failed_tests[@]}"; do
		echo "  ${test}"
	done
	exit 1
fi
