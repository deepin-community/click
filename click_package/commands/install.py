# Copyright (C) 2013 Canonical Ltd.
# Author: Colin Watson <cjwatson@ubuntu.com>

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

"""Install a Click package (low-level; consider pkcon instead)."""

from __future__ import print_function

from optparse import OptionParser
import sys
from textwrap import dedent

from gi.repository import Click

from click_package.install import ClickInstaller, ClickInstallerError


def run(argv):
    parser = OptionParser(dedent("""\
        %prog install [options] PACKAGE-FILE

        This is a low-level tool; to install a package as an ordinary user
        you should generally use "pkcon install-local PACKAGE-FILE"
        instead."""))
    parser.add_option(
        "--root", metavar="PATH", help="install packages underneath PATH")
    parser.add_option(
        "--force-missing-framework", action="store_true", default=False,
        help="install despite missing system framework")
    parser.add_option(
        "--user", metavar="USER", help="register package for USER")
    parser.add_option(
        "--all-users", default=False, action="store_true",
        help="register package for all users")
    parser.add_option(
        "--allow-unauthenticated", default=False, action="store_true",
        help="allow installing packages with no signatures")
    parser.add_option(
        "--verbose", default=False, action="store_true",
        help="be more verbose on install")
    options, args = parser.parse_args(argv)
    if len(args) < 1:
        parser.error("need package file name")
    db = Click.DB()
    db.read(db_dir=None)
    if options.root is not None:
        db.add(options.root)
    package_path = args[0]
    installer = ClickInstaller(
        db=db, force_missing_framework=options.force_missing_framework,
        allow_unauthenticated=options.allow_unauthenticated)
    try:
        installer.install(
            package_path, user=options.user, all_users=options.all_users,
            quiet=not options.verbose)
    except ClickInstallerError as e:
        print("Cannot install %s: %s" % (package_path, e), file=sys.stderr)
        return 1
    return 0
