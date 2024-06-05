#!/bin/sh
#
# test-fixture-wrapper.sh - set up and tear down fixture and execute test
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

base_path="$(realpath "$(dirname "$0")")"
testcase="$(realpath "$1")"
testcase_name="$(basename "${testcase}")"

# create private temporary directory for test cases
TEST_TMPDIR="$(mktemp -d)"
TMPDIR="${TEST_TMPDIR}"
[ $? -eq 0 ] || exit 99
trap 'rm -rf "${TEST_TMPDIR}"' EXIT INT QUIT TERM
export TEST_TMPDIR TMPDIR

if [ -d "${base_path}/dbs/${testcase_name}.preinstalled" ]; then
    CLICK_SERVICE_TEST_DB_PATHS="${base_path}/dbs/${testcase_name}.preinstalled"
fi

if [ -d "${base_path}/dbs/${testcase_name}.in" ]; then
    cp -r "${base_path}/dbs/${testcase_name}.in" "${TEST_TMPDIR}/clicks"
    if [ -d "${TEST_TMPDIR}/clicks/.click/users/@user" ]; then
        mv "${TEST_TMPDIR}/clicks/.click/users/@user" \
            "${TEST_TMPDIR}/clicks/.click/users/${USER}"
    fi

    CLICK_SERVICE_TEST_DB_PATHS="${CLICK_SERVICE_TEST_DB_PATHS:+${CLICK_SERVICE_TEST_DB_PATHS}:}${TEST_TMPDIR}/clicks"
fi

export CLICK_SERVICE_TEST_DB_PATHS

# set up path so the mock click command is used
PATH="${base_path}/bin:${PATH}" "${base_path}/../click-service" --debug &
pid=$!
trap 'kill -15 "${pid}"; rm -rf "${TEST_TMPDIR}"' EXIT INT QUIT TERM

gdbus wait --system com.lomiri.click

"${testcase}"
