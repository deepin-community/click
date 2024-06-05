#!/bin/sh
#
# test-runner.sh - set up private DBus instance and execute the fixture wrapper
#
# Copyright (C) 2023 Guido Berhoerster <guido+ubports@berhoerster.name>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

set -x

LC_ALL=C

fixture_wrapper="$(realpath "$(dirname "$0")")/test-fixure-wrapper.sh"
testcase="$(realpath "$1")"

[ -d /proc/1 ] || exit 99
[ -x "${fixture_wrapper}" ] || exit 99
if [ ! -x "${testcase}" ] || [ ! -f "${testcase}" ]; then
    exit 99
fi

# run wrapper which sets up the test fixture
exec dbus-test-runner \
    --bus-type=system \
    --task="${fixture_wrapper}" \
    --parameter="${testcase}" \
    --task-name="$(basename "${testcase}")" \
    --max-wait=300
