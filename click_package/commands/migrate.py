# Copyright (C) 2022 UBports Foundation.
# Author: Marius Gripsgard <marius@ubports.com>

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

"""Migrate Click packages."""

from optparse import OptionParser
import os
import pwd

from gi.repository import Click, Gio

from click_package.json_helpers import json_array_to_python


def remove_package(db, package, options):
    # Remove the package from both @all and user's DB. This should be fine
    # even if another user needs migration for an app in @all too, since
    # data migration doesn't depend on the old app actually installed.

    for registry in (
        Click.User.for_all_users(db),
        Click.User.for_user(db, name=options.for_user)
    ):
        try:
            old_version = registry.get_version(package)
            print(f"Removing {package} {old_version} for "
                  f"'{'@all' if registry.props.is_pseudo_user else options.for_user}'")
            registry.remove(package)
            db.maybe_remove(package, old_version)
        except:
            pass

def migrate_folder(folder_from, folder_to):
    if not os.path.exists(folder_from):
        print("Old data path does not exist", folder_from)
        return False
    if os.path.exists(folder_to):
        print("Data alredy exists in new location, do not migrate data")
        return False
    print("Rename from to", folder_from, folder_to)
    os.rename(folder_from, folder_to)
    return True

def do_launcher_migration(old_name, name):
    gsettings = Gio.Settings.new("com.lomiri.Shell.Launcher")

    default_items = list(gsettings.get_default_value("items"))
    items = gsettings.get_strv("items")
    if default_items == items:
        print("Gsettings items are default values, do not migrate")
        return

    # As lomiri will write items as appid://* and not the older application:/// or appid://package/app/version
    # see: https://gitlab.com/ubports/development/core/lomiri/-/blob/main/plugins/Lomiri/Launcher/gsettings.cpp#L63
    # So if this has been modifed it will be stored like this, so only account for that format
    new_appid = "appid://{}".format(name)

    for (i, item) in enumerate(items):
        if not item.startswith("appid://"):
            continue

        item_name = item.replace("appid://", "").split("/")[0]
        if item_name == old_name:
            print("migrating {} to {}".format(old_name, name))
            gsettings.set_strv("items", items[:i]+[new_appid]+items[i+1:])
    gsettings.sync()

# Migrates:
#  @{HOME}/.cache/@{APP_PKGNAME}/
#  @{HOME}/.config/@{APP_PKGNAME}/
#  @{HOME}/.local/share/@{APP_PKGNAME}
def do_name_migration(db, old_name, name, options):
    user_folder = pwd.getpwnam(options.for_user).pw_dir
    for path in [".cache", ".config", ".local/share"]:
        prefix = os.path.join(user_folder, path)
        folder_from = os.path.join(prefix, old_name)
        folder_to = os.path.join(prefix, name)
        migrate_folder(folder_from, folder_to)
    remove_package(db, old_name, options)


def do_migration(db, package, options):
    migrations = package.get("migrations")
    print(migrations)
    if "old-name" in migrations:
        print("Doing old name migration")
        do_name_migration(db, migrations.get("old-name"), package.get("name"), options)
        do_launcher_migration(migrations.get("old-name"), package.get("name"))

def run(argv):
    parser = OptionParser("%prog migrate [options]")

    parser.add_option(
        "--for-user", metavar="USER",
        help="Do data migration and package removal for USER (if you have permission) "
             "(default: SUDO_USER)")

    options, _ = parser.parse_args(argv)

    if options.for_user is None and "SUDO_USER" in os.environ:
        options.for_user = os.environ["SUDO_USER"]

    try:
        pwd.getpwnam(options.for_user)
    except:
        parser.error("{} is not a valid user".format(options.for_user))
        return 1

    db = Click.DB()
    db.read(db_dir=None)

    # Gets all installed packages across all registries (@all and every user).
    # Should be fine even if it includes applications from other users; the
    # migration should do nothing in that case.
    pkgs = json_array_to_python(db.get_manifests(all_versions=True))

    # Migration format
    # "migrations": {
    #      "old-name": "old.package.name"
    # }

    pkg_migrate = []
    for pkg in pkgs:
        if not "migrations" in pkg:
            continue

        # TODO Allow other apps to migrate (but user has to confirm)
        # this can be done on open-store installs and not on startup

        pkg_migrate.append(pkg.get("name"))
        do_migration(db, pkg, options)

    if len(pkg_migrate) == 0:
        print("No packages to migrate")
    else:
        print("Migrated:", ", ".join(pkg_migrate))

    return 0
