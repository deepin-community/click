#!/bin/sh

set -x

out="$(gdbus call --system \
    --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Install \
    "/nonexistent/bar.ubports_1.0_arm64.click" 2>&1)"
[ $? -eq 1 ] || exit 1
case $out in
*"failed to open "*"/bar.ubports_1.0_arm64.click")
    ;;
*)
    exit 1
esac
