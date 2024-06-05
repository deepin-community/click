#!/bin/sh

set -x

gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Remove \
    "inall.ubports"
status=$?
[ $status -eq 0 ] || exit $status

! [ -e "${TEST_TMPDIR}/clicks/inall.ubports/0.1" ] || exit 1
! [ -h "${TEST_TMPDIR}/clicks/.click/users/@all/inall.ubports" ] || exit 1

gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Remove \
    "inuser.ubports"
status=$?
[ $status -eq 0 ] || exit $status

! [ -e "${TEST_TMPDIR}/clicks/inuser.ubports/0.2" ] || exit 1
! [ -h "${TEST_TMPDIR}/clicks/.click/users/${USER}/inuser.ubports" ] || exit 1

gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Remove \
    "inboth.ubports"
status=$?
[ $status -eq 0 ] || exit $status

! [ -e "${TEST_TMPDIR}/clicks/inboth.ubports/0.1" ] || exit 1
! [ -h "${TEST_TMPDIR}/clicks/.click/users/@all/inboth.ubports" ] || exit 1
! [ -h "${TEST_TMPDIR}/clicks/.click/users/${USER}/inboth.ubports" ] || exit 1
