#!/bin/sh

set -x

touch "${TEST_TMPDIR}/foo.ubports_1.0_arm64.click"

gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Install \
    "${TEST_TMPDIR}/foo.ubports_1.0_arm64.click"
status=$?
[ $status -eq 0 ] || exit $status

grep -qF -- 'invocation: click install --all-users --allow-unauthenticated' \
    "${TEST_TMPDIR}/click.log" || exit 1
grep -qF foo.ubports_1.0_arm64.click "${TEST_TMPDIR}/click.log" || exit 1
