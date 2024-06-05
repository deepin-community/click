#!/bin/sh

set -x

output=$(gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Remove \
    "bar.ubports" 2>&1)
status=$?
echo "$output"

[ $status -eq 1 ] || exit $status

[ "$(echo "$output" | grep -c -F -- 'bar.ubports does not exist')" = 1 ] || exit 1
