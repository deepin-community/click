#!/bin/sh

set -x

gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Remove \
    "preinstalled.ubports"
status=$?
[ $status -eq 0 ] || exit $status

[ "$(readlink "${TEST_TMPDIR}/clicks/.click/users/@all/preinstalled.ubports")" = "@hidden" ] || exit 1
! [ -h "${TEST_TMPDIR}/clicks/.click/users/${USER}/preinstalled.ubports" ] || exit 1

output=$(gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Remove \
    "preinstalled.ubports" 2>&1)
status=$?
echo "$output"

[ $status -eq 1 ] || exit $status

[ "$(echo "$output" | grep -c -F -- 'preinstalled.ubports is hidden')" = 1 ] || exit 1

# Removing an upgraded app is supposed to expose the underlay (preinstalled)
# version of the app i.e. no @hidden anywhere.
for u in all user both; do
    gdbus call --system \
        --dest com.lomiri.click \
        --object-path /com/lomiri/click \
        --method com.lomiri.click.Remove \
        "${u}.upgraded.ubports"
    status=$?
    [ $status -eq 0 ] || exit $status

    ! [ -h "${TEST_TMPDIR}/clicks/.click/users/@all/${u}.upgraded.ubports" ] || exit 1
    ! [ -h "${TEST_TMPDIR}/clicks/.click/users/${USER}/${u}.upgraded.ubports" ] || exit 1
done
