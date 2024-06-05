#!/bin/sh

set -x

touch "${TEST_TMPDIR}/foo.ubports_1.0_arm64.click"
chmod 000 "${TEST_TMPDIR}/foo.ubports_1.0_arm64.click"

out="$(gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Install \
    "${TEST_TMPDIR}/foo.ubports_1.0_arm64.click" 2>&1)"
[ $? -eq 1 ] || exit 1
case $out in
*"failed to open "*"/foo.ubports_1.0_arm64.click")
    ;;
*)
    exit 1
esac
