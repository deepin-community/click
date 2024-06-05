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

"""Unit tests for click_package.hooks."""

from __future__ import print_function

__metaclass__ = type
__all__ = [
    "TestClickHookSystemLevel",
    "TestClickHookUserLevel",
    "TestClickPatternFormatter",
    "TestPackageInstallHooks",
    "TestPackageRemoveHooks",
    ]


from functools import partial
from itertools import takewhile
import json
import os
from textwrap import dedent

from gi.repository import Click, GLib

from click_package.tests.gimock_types import Passwd
from click_package.tests.helpers import TestCase, mkfile, mkfile_utf8


class TestClickPatternFormatter(TestCase):
    def _make_variant(self, **kwargs):
        # pygobject's Variant creator can't handle maybe types, so we have
        # to do this by hand.
        builder = GLib.VariantBuilder.new(GLib.VariantType.new("a{sms}"))
        for key, value in kwargs.items():
            entry = GLib.VariantBuilder.new(GLib.VariantType.new("{sms}"))
            entry.add_value(GLib.Variant.new_string(key))
            entry.add_value(GLib.Variant.new_maybe(
                GLib.VariantType.new("s"),
                None if value is None else GLib.Variant.new_string(value)))
            builder.add_value(entry.end())
        return builder.end()

    def test_expands_provided_keys(self):
        self.assertEqual(
            "foo.bar",
            Click.pattern_format("foo.${key}", self._make_variant(key="bar")))
        self.assertEqual(
            "foo.barbaz",
            Click.pattern_format(
                "foo.${key1}${key2}",
                self._make_variant(key1="bar", key2="baz")))

    def test_expands_missing_keys_to_empty_string(self):
        self.assertEqual(
            "xy", Click.pattern_format("x${key}y", self._make_variant()))

    def test_preserves_unmatched_dollar(self):
        self.assertEqual("$", Click.pattern_format("$", self._make_variant()))
        self.assertEqual(
            "$ {foo}", Click.pattern_format("$ {foo}", self._make_variant()))
        self.assertEqual(
            "x${y",
            Click.pattern_format("${key}${y", self._make_variant(key="x")))

    def test_double_dollar(self):
        self.assertEqual("$", Click.pattern_format("$$", self._make_variant()))
        self.assertEqual(
            "${foo}", Click.pattern_format("$${foo}", self._make_variant()))
        self.assertEqual(
            "x$y",
            Click.pattern_format("x$$${key}", self._make_variant(key="y")))

    def test_possible_expansion(self):
        self.assertEqual(
            {"id": "abc"},
            Click.pattern_possible_expansion(
                "x_abc_1", "x_${id}_${num}",
                self._make_variant(num="1")).unpack())
        self.assertIsNone(
            Click.pattern_possible_expansion(
                "x_abc_1", "x_${id}_${num}", self._make_variant(num="2")))


class TestClickHookBase(TestCase):

    TEST_USER = "test-user"

    def setUp(self):
        super(TestClickHookBase, self).setUp()
        self.use_temp_dir()
        self.db = Click.DB()
        self.db.add(self.temp_dir)
        self.spawn_calls = []

    def _make_installed_click(self, package="test-1", version="1.0",
                              json_data={},
                              make_current=True,
                              all_users=False):
        with mkfile_utf8(os.path.join(
                self.temp_dir, package, version, ".click", "info",
                "%s.manifest" % package)) as f:
            json.dump(json_data, f, ensure_ascii=False)
        if make_current:
            os.symlink(
                version, os.path.join(self.temp_dir, package, "current"))
        if all_users:
            db = Click.User.for_all_users(self.db)
        else:
            db = Click.User.for_user(self.db, self.TEST_USER)
        db.set_version(package, version)

    def _make_hook_file(self, content, hookname="test"):
        hook_file = os.path.join(self.hooks_dir, "%s.hook" % hookname)
        with mkfile(hook_file) as f:
            print(content, file=f)

    def _setup_hooks_dir(self, preloads, hooks_dir=None):
        if hooks_dir is None:
            hooks_dir = self.temp_dir
        preloads["click_get_hooks_dir"].side_effect = (
            lambda: self.make_string(hooks_dir))
        self.hooks_dir = hooks_dir

    def g_spawn_sync_side_effect(self, status_map, working_directory, argv,
                                 envp, flags, child_setup, user_data,
                                 standard_output, standard_error, exit_status,
                                 error):
        self.spawn_calls.append(list(takewhile(lambda x: x is not None, argv)))
        if argv[0] in status_map:
            exit_status[0] = status_map[argv[0]]
        else:
            self.delegate_to_original("g_spawn_sync")
        return 0


class TestClickHookSystemLevel(TestClickHookBase):
    def test_open(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                    Pattern: /usr/share/test/${id}.test
                    # Comment
                    Exec: test-update
                    User: root
                    """))
            hook = Click.Hook.open(self.db, "test")
            self.assertCountEqual(
                ["pattern", "exec", "user"], hook.get_fields())
            self.assertEqual(
                "/usr/share/test/${id}.test", hook.get_field("pattern"))
            self.assertEqual("test-update", hook.get_field("exec"))
            self.assertRaisesHooksError(
                Click.HooksError.MISSING_FIELD, hook.get_field, "nonexistent")
            self.assertFalse(hook.props.is_user_level)

    def test_open_unopenable_file(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            os.symlink("nonexistent", os.path.join(self.hooks_dir, "foo.hook"))
            self.assertRaisesHooksError(
                Click.HooksError.NO_SUCH_HOOK, Click.Hook.open, self.db, "foo")

    def test_hook_name_absent(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(
                "Pattern: /usr/share/test/${id}.test")
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual("test", hook.get_hook_name())

    def test_hook_name_present(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                Pattern: /usr/share/test/${id}.test
                Hook-Name: other"""))
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual("other", hook.get_hook_name())

    def test_invalid_app_id(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                    Pattern: /usr/share/test/${id}.test
                    # Comment
                    Exec: test-update
                    User: root
            """))
            hook = Click.Hook.open(self.db, "test")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_app_id,
                "package", "0.1", "app_name")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_app_id,
                "package", "0.1", "app/name")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_pattern,
                "package", "0.1", "app_name")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_pattern,
                "package", "0.1", "app/name")

    def test_short_id_invalid(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(
                "Pattern: /usr/share/test/${short-id}.test")
            hook = Click.Hook.open(self.db, "test")
            # It would perhaps be better if unrecognised $-expansions raised
            # KeyError, but they don't right now.
            self.assertEqual(
                "/usr/share/test/.test",
                hook.get_pattern("package", "0.1", "app-name", user_name=None))

    def test_short_id_valid_with_single_version(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                Pattern: /usr/share/test/${short-id}.test
                Single-Version: yes"""))
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual(
                "/usr/share/test/package_app-name.test",
                hook.get_pattern("package", "0.1", "app-name", user_name=None))

    def test_run_commands(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "g_spawn_sync") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["g_spawn_sync"].side_effect = partial(
                self.g_spawn_sync_side_effect, {b"/bin/sh": 0})
            with mkfile(os.path.join(self.temp_dir, "test.hook")) as f:
                print("Exec: test-update", file=f)
                print("User: root", file=f)
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual(
                "root", hook.get_run_commands_user(user_name=None))
            hook.run_commands(user_name=None)
            self.assertEqual(
                [[b"/bin/sh", b"-c", b"test-update"]], self.spawn_calls)

    def test_run_commands_fail(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "g_spawn_sync") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["g_spawn_sync"].side_effect = partial(
                self.g_spawn_sync_side_effect, {b"/bin/sh": 1})
            with mkfile(os.path.join(self.temp_dir, "test.hook")) as f:
                print("Exec: test-update", file=f)
                print("User: root", file=f)
            hook = Click.Hook.open(self.db, "test")
            self.assertRaisesHooksError(
                Click.HooksError.COMMAND_FAILED, hook.run_commands,
                user_name=None)

    def test_install_package(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(
                "Pattern: %s/${id}.test" % self.temp_dir)
            os.makedirs(
                os.path.join(self.temp_dir, "org.example.package", "1.0"))
            hook = Click.Hook.open(self.db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo/bar",
                user_name=None)
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            target_path = os.path.join(
                self.temp_dir, "org.example.package", "1.0", "foo", "bar")
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(target_path, os.readlink(symlink_path))

    def test_install_package_trailing_slash(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(
                "Pattern: %s/${id}/" % self.temp_dir)
            os.makedirs(
                os.path.join(self.temp_dir, "org.example.package", "1.0"))
            hook = Click.Hook.open(self.db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo",
                user_name=None)
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0")
            target_path = os.path.join(
                self.temp_dir, "org.example.package", "1.0", "foo")
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(target_path, os.readlink(symlink_path))

    def test_install_package_uses_deepest_copy(self):
        # If the same version of a package is unpacked in multiple
        # databases, then we make sure the link points to the deepest copy,
        # even if it already points somewhere else.  It is important to be
        # consistent about this since system hooks may only have a single
        # target for any given application ID.
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(
                "Pattern: %s/${id}.test" % self.temp_dir)
            underlay = os.path.join(self.temp_dir, "underlay")
            overlay = os.path.join(self.temp_dir, "overlay")
            db = Click.DB()
            db.add(underlay)
            db.add(overlay)
            os.makedirs(os.path.join(underlay, "org.example.package", "1.0"))
            os.makedirs(os.path.join(overlay, "org.example.package", "1.0"))
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            underlay_target_path = os.path.join(
                underlay, "org.example.package", "1.0", "foo")
            overlay_target_path = os.path.join(
                overlay, "org.example.package", "1.0", "foo")
            os.symlink(overlay_target_path, symlink_path)
            hook = Click.Hook.open(db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo",
                user_name=None)
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(underlay_target_path, os.readlink(symlink_path))

    def test_upgrade(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(
                "Pattern: %s/${id}.test" % self.temp_dir)
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            os.symlink("old-target", symlink_path)
            os.makedirs(
                os.path.join(self.temp_dir, "org.example.package", "1.0"))
            hook = Click.Hook.open(self.db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo/bar",
                user_name=None)
            target_path = os.path.join(
                self.temp_dir, "org.example.package", "1.0", "foo", "bar")
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(target_path, os.readlink(symlink_path))

    def test_remove_package(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(
                "Pattern: %s/${id}.test" % self.temp_dir)
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            os.symlink("old-target", symlink_path)
            hook = Click.Hook.open(self.db, "test")
            hook.remove_package(
                "org.example.package", "1.0", "test-app", user_name=None)
            self.assertFalse(os.path.exists(symlink_path))

    def test_install(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(
                preloads, hooks_dir=os.path.join(self.temp_dir, "hooks"))
            self._make_hook_file(
                "Pattern: %s/${id}.new" % self.temp_dir,
                hookname="new")
            self._make_installed_click("test-1", "1.0", json_data={
                    "maintainer":
                        b"Unic\xc3\xb3de <unicode@example.org>".decode(
                            "UTF-8"),
                    "hooks": {"test1-app": {"new": "target-1"}}})
            self._make_installed_click("test-2", "2.0", json_data={
                    "maintainer":
                        b"Unic\xc3\xb3de <unicode@example.org>".decode(
                            "UTF-8"),
                    "hooks": {"test1-app": {"new": "target-2"}},
                })
            hook = Click.Hook.open(self.db, "new")
            hook.install(user_name=None)
            path_1 = os.path.join(self.temp_dir, "test-1_test1-app_1.0.new")
            self.assertTrue(os.path.lexists(path_1))
            self.assertEqual(
                os.path.join(self.temp_dir, "test-1", "1.0", "target-1"),
                os.readlink(path_1))
            path_2 = os.path.join(self.temp_dir, "test-2_test1-app_2.0.new")
            self.assertTrue(os.path.lexists(path_2))
            self.assertEqual(
                os.path.join(self.temp_dir, "test-2", "2.0", "target-2"),
                os.readlink(path_2))

    def test_remove(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(
                preloads, hooks_dir=os.path.join(self.temp_dir, "hooks"))
            self._make_hook_file(
                "Pattern: %s/${id}.old" % self.temp_dir,
                hookname="old")
            self._make_installed_click("test-1", "1.0", json_data={
                "hooks": {"test1-app": {"old": "target-1"}}})
            path_1 = os.path.join(self.temp_dir, "test-1_test1-app_1.0.old")
            os.symlink(
                os.path.join(self.temp_dir, "test-1", "1.0", "target-1"),
                path_1)
            self._make_installed_click("test-2", "2.0", json_data={
                "hooks": {"test2-app": {"old": "target-2"}}})
            path_2 = os.path.join(self.temp_dir, "test-2_test2-app_2.0.old")
            os.symlink(
                os.path.join(self.temp_dir, "test-2", "2.0", "target-2"),
                path_2)
            hook = Click.Hook.open(self.db, "old")
            hook.remove(user_name=None)
            self.assertFalse(os.path.exists(path_1))
            self.assertFalse(os.path.exists(path_2))

    def test_sync(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(
                preloads, hooks_dir=os.path.join(self.temp_dir, "hooks"))
            self._make_hook_file(
                "Pattern: %s/${id}.test" % self.temp_dir)
            self._make_installed_click("test-1", "1.0", json_data={
                "hooks": {"test1-app": {"test": "target-1"}}})
            self._make_installed_click(
                "test-2", "1.0", make_current=False,
                json_data={"hooks": {"test2-app": {"test": "target-2"}}})
            self._make_installed_click("test-2", "1.1", json_data={
                "hooks": {"test2-app": {"test": "target-2"}}})
            path_1 = os.path.join(self.temp_dir, "test-1_test1-app_1.0.test")
            os.symlink(
                os.path.join(self.temp_dir, "test-1", "1.0", "target-1"),
                path_1)
            path_2_1_0 = os.path.join(
                self.temp_dir, "test-2_test2-app_1.0.test")
            path_2_1_1 = os.path.join(
                self.temp_dir, "test-2_test2-app_1.1.test")
            path_3 = os.path.join(self.temp_dir, "test-3_test3-app_1.0.test")
            os.symlink(
                os.path.join(self.temp_dir, "test-3", "1.0", "target-3"),
                path_3)
            hook = Click.Hook.open(self.db, "test")
            hook.sync(user_name=None)
            self.assertTrue(os.path.lexists(path_1))
            self.assertEqual(
                os.path.join(self.temp_dir, "test-1", "1.0", "target-1"),
                os.readlink(path_1))
            self.assertTrue(os.path.lexists(path_2_1_0))
            self.assertEqual(
                os.path.join(self.temp_dir, "test-2", "1.0", "target-2"),
                os.readlink(path_2_1_0))
            self.assertTrue(os.path.lexists(path_2_1_1))
            self.assertEqual(
                os.path.join(self.temp_dir, "test-2", "1.1", "target-2"),
                os.readlink(path_2_1_1))
            self.assertFalse(os.path.lexists(path_3))


class TestClickHookUserLevel(TestClickHookBase):
    def test_open(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                    User-Level: yes
                    Pattern: ${home}/.local/share/test/${id}.test
                    # Comment
                    Exec: test-update
                    """))
            hook = Click.Hook.open(self.db, "test")
            self.assertCountEqual(
                ["user-level", "pattern", "exec"], hook.get_fields())
            self.assertEqual(
                "${home}/.local/share/test/${id}.test",
                hook.get_field("pattern"))
            self.assertEqual("test-update", hook.get_field("exec"))
            self.assertRaisesHooksError(
                Click.HooksError.MISSING_FIELD, hook.get_field, "nonexistent")
            self.assertTrue(hook.props.is_user_level)

    def test_hook_name_absent(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: ${home}/.local/share/test/${id}.test"""))
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual("test", hook.get_hook_name())

    def test_hook_name_present(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: ${home}/.local/share/test/${id}.test
                Hook-Name: other"""))
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual("other", hook.get_hook_name())

    def test_invalid_app_id(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            self._make_hook_file(dedent("""\
                    User-Level: yes
                    Pattern: ${home}/.local/share/test/${id}.test
                    # Comment
                    Exec: test-update"""))
            hook = Click.Hook.open(self.db, "test")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_app_id,
                "package", "0.1", "app_name")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_app_id,
                "package", "0.1", "app/name")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_pattern,
                "package", "0.1", "app_name")
            self.assertRaisesHooksError(
                Click.HooksError.BAD_APP_NAME, hook.get_pattern,
                "package", "0.1", "app/name")

    def test_short_id_valid(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "getpwnam") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["getpwnam"].side_effect = (
                lambda name: self.make_pointer(Passwd(pw_dir=b"/mock")))
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: ${home}/.local/share/test/${short-id}.test
            """))
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual(
                "/mock/.local/share/test/package_app-name.test",
                hook.get_pattern(
                    "package", "0.1", "app-name", user_name="mock"))

    def test_run_commands(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "g_spawn_sync") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["g_spawn_sync"].side_effect = partial(
                self.g_spawn_sync_side_effect, {b"/bin/sh": 0})
            with mkfile(os.path.join(self.temp_dir, "test.hook")) as f:
                print("User-Level: yes", file=f)
                print("Exec: test-update", file=f)
            hook = Click.Hook.open(self.db, "test")
            self.assertEqual(
                self.TEST_USER,
                hook.get_run_commands_user(user_name=self.TEST_USER))
            hook.run_commands(user_name=self.TEST_USER)
            self.assertEqual(
                [[b"/bin/sh", b"-c", b"test-update"]], self.spawn_calls)

    def test_run_commands_fail(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "g_spawn_sync") as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["g_spawn_sync"].side_effect = partial(
                self.g_spawn_sync_side_effect, {b"/bin/sh": 1})
            with mkfile(os.path.join(self.temp_dir, "test.hook")) as f:
                print("User-Level: yes", file=f)
                print("Exec: test-update", file=f)
            hook = Click.Hook.open(self.db, "test")
            self.assertRaisesHooksError(
                Click.HooksError.COMMAND_FAILED, hook.run_commands,
                user_name=self.TEST_USER)

    def test_install_package(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            os.makedirs(os.path.join(
                self.temp_dir, "org.example.package", "1.0"))
            user_db = Click.User.for_user(self.db, self.TEST_USER)
            user_db.set_version("org.example.package", "1.0")
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: %s/${id}.test""") % self.temp_dir)
            hook = Click.Hook.open(self.db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo/bar",
                user_name=self.TEST_USER)
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            target_path = os.path.join(
                self.temp_dir, ".click", "users", self.TEST_USER,
                "org.example.package", "foo", "bar")
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(target_path, os.readlink(symlink_path))

    def test_install_package_trailing_slash(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            os.makedirs(os.path.join(
                self.temp_dir, "org.example.package", "1.0"))
            user_db = Click.User.for_user(self.db, self.TEST_USER)
            user_db.set_version("org.example.package", "1.0")
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: %s/${id}/""") % self.temp_dir)
            hook = Click.Hook.open(self.db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo",
                user_name=self.TEST_USER)
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0")
            target_path = os.path.join(
                self.temp_dir, ".click", "users", self.TEST_USER,
                "org.example.package", "foo")
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(target_path, os.readlink(symlink_path))

    def test_install_package_removes_previous(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            os.makedirs(os.path.join(
                self.temp_dir, "org.example.package", "1.0"))
            os.makedirs(os.path.join(
                self.temp_dir, "org.example.package", "1.1"))
            user_db = Click.User.for_user(self.db, self.TEST_USER)
            user_db.set_version("org.example.package", "1.0")
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: %s/${id}.test""") % self.temp_dir)
            hook = Click.Hook.open(self.db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo/bar",
                user_name=self.TEST_USER)
            hook.install_package(
                "org.example.package", "1.1", "test-app", "foo/bar",
                user_name=self.TEST_USER)
            old_symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.1.test")
            self.assertFalse(os.path.islink(old_symlink_path))
            self.assertTrue(os.path.islink(symlink_path))
            target_path = os.path.join(
                self.temp_dir, ".click", "users", self.TEST_USER,
                "org.example.package", "foo", "bar")
            self.assertEqual(target_path, os.readlink(symlink_path))

    def test_upgrade(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            os.symlink("old-target", symlink_path)
            os.makedirs(os.path.join(
                self.temp_dir, "org.example.package", "1.0"))
            user_db = Click.User.for_user(self.db, self.TEST_USER)
            user_db.set_version("org.example.package", "1.0")
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: %s/${id}.test""") % self.temp_dir)
            hook = Click.Hook.open(self.db, "test")
            hook.install_package(
                "org.example.package", "1.0", "test-app", "foo/bar",
                user_name=self.TEST_USER)
            target_path = os.path.join(
                self.temp_dir, ".click", "users", self.TEST_USER,
                "org.example.package", "foo", "bar")
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(target_path, os.readlink(symlink_path))

    def test_remove_package(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            self._make_hook_file(dedent("""\
                User-Level: yes
                Pattern: %s/${id}.test""") % self.temp_dir)
            symlink_path = os.path.join(
                self.temp_dir, "org.example.package_test-app_1.0.test")
            os.symlink("old-target", symlink_path)
            hook = Click.Hook.open(self.db, "test")
            hook.remove_package(
                "org.example.package", "1.0", "test-app",
                user_name=self.TEST_USER)
            self.assertFalse(os.path.exists(symlink_path))

    def test_install(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home", "getpwnam"
                ) as (enter, preloads):
            enter()
            # Don't tell click about the hooks directory yet.
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            preloads["getpwnam"].side_effect = (
                lambda name: self.make_pointer(Passwd(pw_uid=1, pw_gid=1)))
            with mkfile(os.path.join(self.temp_dir, "hooks", "new.hook")) as f:
                print("User-Level: yes", file=f)
                print("Pattern: %s/${id}.new" % self.temp_dir, file=f)
            self._make_installed_click("test-1", "1.0", json_data={
                    "maintainer":
                        b"Unic\xc3\xb3de <unicode@example.org>".decode(
                            "UTF-8"),
                    "hooks": {"test1-app": {"new": "target-1"}},
            })
            self._make_installed_click("test-2", "2.0", json_data={
                    "maintainer":
                        b"Unic\xc3\xb3de <unicode@example.org>".decode(
                            "UTF-8"),
                    "hooks": {"test1-app": {"new": "target-2"}},
                })
            # Now tell click about the hooks directory and make sure it
            # catches up correctly.
            self._setup_hooks_dir(
                preloads, hooks_dir=os.path.join(self.temp_dir, "hooks"))
            hook = Click.Hook.open(self.db, "new")
            hook.install(user_name=None)
            path_1 = os.path.join(self.temp_dir, "test-1_test1-app_1.0.new")
            self.assertTrue(os.path.lexists(path_1))
            self.assertEqual(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-1",
                    "target-1"),
                os.readlink(path_1))
            path_2 = os.path.join(self.temp_dir, "test-2_test1-app_2.0.new")
            self.assertTrue(os.path.lexists(path_2))
            self.assertEqual(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-2",
                    "target-2"),
                os.readlink(path_2))

            os.unlink(path_1)
            os.unlink(path_2)
            hook.install(user_name="another-user")
            self.assertFalse(os.path.lexists(path_1))
            self.assertFalse(os.path.lexists(path_2))

            hook.install(user_name=self.TEST_USER)
            self.assertTrue(os.path.lexists(path_1))
            self.assertEqual(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-1",
                    "target-1"),
                os.readlink(path_1))
            self.assertTrue(os.path.lexists(path_2))
            self.assertEqual(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-2",
                    "target-2"),
                os.readlink(path_2))

    def test_remove(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            # Don't tell click about the hooks directory yet.
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            with mkfile(os.path.join(self.temp_dir, "hooks", "old.hook")) as f:
                print("User-Level: yes", file=f)
                print("Pattern: %s/${id}.old" % self.temp_dir, file=f)
            user_db = Click.User.for_user(self.db, self.TEST_USER)
            self._make_installed_click("test-1", "1.0", json_data={
                "hooks": {"test1-app": {"old": "target-1"}}})
            path_1 = os.path.join(self.temp_dir, "test-1_test1-app_1.0.old")
            os.symlink(
                os.path.join(user_db.get_path("test-1"), "target-1"), path_1)
            self._make_installed_click("test-2", "2.0", json_data={
                "hooks": {"test2-app": {"old": "target-2"}}})
            path_2 = os.path.join(self.temp_dir, "test-2_test2-app_2.0.old")
            os.symlink(
                os.path.join(user_db.get_path("test-2"), "target-2"), path_2)
            # Now tell click about the hooks directory and make sure it
            # catches up correctly.
            self._setup_hooks_dir(
                preloads, hooks_dir=os.path.join(self.temp_dir, "hooks"))
            hook = Click.Hook.open(self.db, "old")
            hook.remove(user_name=None)
            self.assertFalse(os.path.exists(path_1))
            self.assertFalse(os.path.exists(path_2))

    def test_sync(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            self._setup_hooks_dir(preloads)
            with mkfile(
                    os.path.join(self.temp_dir, "hooks", "test.hook")) as f:
                print("User-Level: yes", file=f)
                print("Pattern: %s/${id}.test" % self.temp_dir, file=f)
            self._make_installed_click("test-1", "1.0", json_data={
                "hooks": {"test1-app": {"test": "target-1"}}})
            self._make_installed_click("test-2", "1.1", json_data={
                "hooks": {"test2-app": {"test": "target-2"}}})
            path_1 = os.path.join(self.temp_dir, "test-1_test1-app_1.0.test")
            os.symlink(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-1",
                    "target-1"),
                path_1)
            path_2 = os.path.join(self.temp_dir, "test-2_test2-app_1.1.test")
            path_3 = os.path.join(self.temp_dir, "test-3_test3-app_1.0.test")
            os.symlink(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-3",
                    "target-3"),
                path_3)
            self._setup_hooks_dir(
                preloads, hooks_dir=os.path.join(self.temp_dir, "hooks"))
            hook = Click.Hook.open(self.db, "test")
            hook.sync(user_name=self.TEST_USER)
            self.assertTrue(os.path.lexists(path_1))
            self.assertEqual(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-1",
                    "target-1"),
                os.readlink(path_1))
            self.assertTrue(os.path.lexists(path_2))
            self.assertEqual(
                os.path.join(
                    self.temp_dir, ".click", "users", self.TEST_USER, "test-2",
                    "target-2"),
                os.readlink(path_2))
            self.assertFalse(os.path.lexists(path_3))

    def test_sync_without_user_db(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            self._setup_hooks_dir(preloads)
            with mkfile(
                    os.path.join(self.temp_dir, "hooks", "test.hook")) as f:
                print("User-Level: yes", file=f)
                print("Pattern: %s/${id}.test" % self.temp_dir, file=f)
            self._make_installed_click(
                "test-package", "1.0", all_users=True, json_data={
                    "hooks": {"test-app": {"test": "target"}}})
            self._setup_hooks_dir(
                preloads, hooks_dir=os.path.join(self.temp_dir, "hooks"))
            hook = Click.Hook.open(self.db, "test")
            hook.sync(user_name=self.TEST_USER)
            self.assertFalse(os.path.exists(os.path.join(
                self.temp_dir, ".click", "users", self.TEST_USER,
                "test-package")))

    def test_sync_uses_deepest_copy(self):
        # If the same version of a package is unpacked in multiple
        # databases, then we make sure the user link points to the deepest
        # copy, even if it already points somewhere else.  It is important
        # to be consistent about this since system hooks may only have a
        # single target for any given application ID, and user links must
        # match system hooks so that (for example) the version of an
        # application run by a user has a matching system AppArmor profile.
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                ) as (enter, preloads):
            enter()
            self._setup_hooks_dir(preloads)
            preloads["click_get_user_home"].return_value = b"/home/test-user"
            with mkfile(os.path.join(self.temp_dir, "test.hook")) as f:
                print("User-Level: yes", file=f)
                print("Pattern: %s/${id}.test" % self.temp_dir, file=f)
            underlay = os.path.join(self.temp_dir, "underlay")
            overlay = os.path.join(self.temp_dir, "overlay")
            db = Click.DB()
            db.add(underlay)
            db.add(overlay)
            underlay_unpacked = os.path.join(underlay, "test-package", "1.0")
            overlay_unpacked = os.path.join(overlay, "test-package", "1.0")
            os.makedirs(underlay_unpacked)
            os.makedirs(overlay_unpacked)
            manifest = {"hooks": {"test-app": {"test": "foo"}}}
            with mkfile(os.path.join(
                    underlay_unpacked, ".click", "info",
                    "test-package.manifest")) as f:
                json.dump(manifest, f)
            with mkfile(os.path.join(
                    overlay_unpacked, ".click", "info",
                    "test-package.manifest")) as f:
                json.dump(manifest, f)
            underlay_user_link = os.path.join(
                underlay, ".click", "users", "@all", "test-package")
            overlay_user_link = os.path.join(
                overlay, ".click", "users", self.TEST_USER, "test-package")
            Click.ensuredir(os.path.dirname(underlay_user_link))
            os.symlink(underlay_unpacked, underlay_user_link)
            Click.ensuredir(os.path.dirname(overlay_user_link))
            os.symlink(overlay_unpacked, overlay_user_link)
            symlink_path = os.path.join(
                self.temp_dir, "test-package_test-app_1.0.test")
            underlay_target_path = os.path.join(underlay_user_link, "foo")
            overlay_target_path = os.path.join(overlay_user_link, "foo")
            os.symlink(overlay_target_path, symlink_path)
            hook = Click.Hook.open(db, "test")
            hook.sync(user_name=self.TEST_USER)
            self.assertTrue(os.path.islink(underlay_user_link))
            self.assertEqual(
                underlay_unpacked, os.readlink(underlay_user_link))
            self.assertFalse(os.path.islink(overlay_user_link))
            self.assertTrue(os.path.islink(symlink_path))
            self.assertEqual(underlay_target_path, os.readlink(symlink_path))


class TestPackageInstallHooks(TestClickHookBase):
    def test_removes_old_hooks(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            hooks_dir = os.path.join(self.temp_dir, "hooks")
            self._setup_hooks_dir(preloads, hooks_dir=hooks_dir)
            with mkfile(os.path.join(hooks_dir, "unity.hook")) as f:
                print("Pattern: %s/unity/${id}.scope" % self.temp_dir, file=f)
                print("Single-Version: yes", file=f)
            with mkfile(os.path.join(hooks_dir, "yelp-docs.hook")) as f:
                print("Pattern: %s/yelp/docs-${id}.txt" % self.temp_dir,
                      file=f)
                print("Single-Version: yes", file=f)
                print("Hook-Name: yelp", file=f)
            with mkfile(os.path.join(hooks_dir, "yelp-other.hook")) as f:
                print("Pattern: %s/yelp/other-${id}.txt" % self.temp_dir,
                      file=f)
                print("Single-Version: yes", file=f)
                print("Hook-Name: yelp", file=f)
            os.mkdir(os.path.join(self.temp_dir, "unity"))
            unity_path = os.path.join(
                self.temp_dir, "unity", "test_app_1.0.scope")
            os.symlink("dummy", unity_path)
            os.mkdir(os.path.join(self.temp_dir, "yelp"))
            yelp_docs_path = os.path.join(
                self.temp_dir, "yelp", "docs-test_app_1.0.txt")
            os.symlink("dummy", yelp_docs_path)
            yelp_other_path = os.path.join(
                self.temp_dir, "yelp", "other-test_app_1.0.txt")
            os.symlink("dummy", yelp_other_path)
            self._make_installed_click("test", "1.0", make_current=False, json_data={
                "hooks": {"app": {"yelp": "foo.txt", "unity": "foo.scope"}}})
            self._make_installed_click("test", "1.1", json_data={})
            Click.package_install_hooks(
                self.db, "test", "1.0", "1.1", user_name=None)
            self.assertFalse(os.path.lexists(unity_path))
            self.assertFalse(os.path.lexists(yelp_docs_path))
            self.assertFalse(os.path.lexists(yelp_other_path))

    def test_installs_new_hooks(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            hooks_dir = os.path.join(self.temp_dir, "hooks")
            self._setup_hooks_dir(preloads, hooks_dir=hooks_dir)
            with mkfile(os.path.join(hooks_dir, "a.hook")) as f:
                print("Pattern: %s/a/${id}.a" % self.temp_dir, file=f)
            with mkfile(os.path.join(hooks_dir, "b-1.hook")) as f:
                print("Pattern: %s/b/1-${id}.b" % self.temp_dir, file=f)
                print("Hook-Name: b", file=f)
            with mkfile(os.path.join(hooks_dir, "b-2.hook")) as f:
                print("Pattern: %s/b/2-${id}.b" % self.temp_dir, file=f)
                print("Hook-Name: b", file=f)
            os.mkdir(os.path.join(self.temp_dir, "a"))
            os.mkdir(os.path.join(self.temp_dir, "b"))
            self._make_installed_click(
                "test", "1.0", make_current=False, json_data={"hooks": {}})
            self._make_installed_click("test", "1.1", json_data={
                "hooks": {"app": {"a": "foo.a", "b": "foo.b"}}})
            Click.package_install_hooks(
                self.db, "test", "1.0", "1.1", user_name=None)
            self.assertTrue(os.path.lexists(
                os.path.join(self.temp_dir, "a", "test_app_1.1.a")))
            self.assertTrue(os.path.lexists(
                os.path.join(self.temp_dir, "b", "1-test_app_1.1.b")))
            self.assertTrue(os.path.lexists(
                os.path.join(self.temp_dir, "b", "2-test_app_1.1.b")))

    def test_upgrades_existing_hooks(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            hooks_dir = os.path.join(self.temp_dir, "hooks")
            self._setup_hooks_dir(preloads, hooks_dir=hooks_dir)
            with mkfile(os.path.join(hooks_dir, "a.hook")) as f:
                print("Pattern: %s/a/${id}.a" % self.temp_dir, file=f)
                print("Single-Version: yes", file=f)
            with mkfile(os.path.join(hooks_dir, "b-1.hook")) as f:
                print("Pattern: %s/b/1-${id}.b" % self.temp_dir, file=f)
                print("Single-Version: yes", file=f)
                print("Hook-Name: b", file=f)
            with mkfile(os.path.join(hooks_dir, "b-2.hook")) as f:
                print("Pattern: %s/b/2-${id}.b" % self.temp_dir, file=f)
                print("Single-Version: yes", file=f)
                print("Hook-Name: b", file=f)
            with mkfile(os.path.join(hooks_dir, "c.hook")) as f:
                print("Pattern: %s/c/${id}.c" % self.temp_dir, file=f)
                print("Single-Version: yes", file=f)
            os.mkdir(os.path.join(self.temp_dir, "a"))
            a_path = os.path.join(self.temp_dir, "a", "test_app_1.0.a")
            os.symlink("dummy", a_path)
            os.mkdir(os.path.join(self.temp_dir, "b"))
            b_irrelevant_path = os.path.join(
                self.temp_dir, "b", "1-test_other-app_1.0.b")
            os.symlink("dummy", b_irrelevant_path)
            b_1_path = os.path.join(self.temp_dir, "b", "1-test_app_1.0.b")
            os.symlink("dummy", b_1_path)
            b_2_path = os.path.join(self.temp_dir, "b", "2-test_app_1.0.b")
            os.symlink("dummy", b_2_path)
            os.mkdir(os.path.join(self.temp_dir, "c"))
            package_dir = os.path.join(self.temp_dir, "test")
            with mkfile(os.path.join(
                    package_dir, "1.0", ".click", "info",
                    "test.manifest")) as f:
                json.dump({"hooks": {"app": {"a": "foo.a", "b": "foo.b"}}}, f)
            with mkfile(os.path.join(
                    package_dir, "1.1", ".click", "info",
                    "test.manifest")) as f:
                json.dump(
                    {"hooks": {
                        "app": {"a": "foo.a", "b": "foo.b", "c": "foo.c"}}
                    }, f)
            Click.package_install_hooks(
                self.db, "test", "1.0", "1.1", user_name=None)
            self.assertFalse(os.path.lexists(a_path))
            self.assertTrue(os.path.lexists(b_irrelevant_path))
            self.assertFalse(os.path.lexists(b_1_path))
            self.assertFalse(os.path.lexists(b_2_path))
            self.assertTrue(os.path.lexists(
                os.path.join(self.temp_dir, "a", "test_app_1.1.a")))
            self.assertTrue(os.path.lexists(
                os.path.join(self.temp_dir, "b", "1-test_app_1.1.b")))
            self.assertTrue(os.path.lexists(
                os.path.join(self.temp_dir, "b", "2-test_app_1.1.b")))
            self.assertTrue(os.path.lexists(
                os.path.join(self.temp_dir, "c", "test_app_1.1.c")))


class TestPackageRemoveHooks(TestClickHookBase):
    def test_removes_hooks(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir") as (enter, preloads):
            enter()
            hooks_dir = os.path.join(self.temp_dir, "hooks")
            self._setup_hooks_dir(preloads, hooks_dir=hooks_dir)
            with mkfile(os.path.join(hooks_dir, "unity.hook")) as f:
                print("Pattern: %s/unity/${id}.scope" % self.temp_dir, file=f)
            with mkfile(os.path.join(hooks_dir, "yelp-docs.hook")) as f:
                print("Pattern: %s/yelp/docs-${id}.txt" % self.temp_dir,
                      file=f)
                print("Hook-Name: yelp", file=f)
            with mkfile(os.path.join(hooks_dir, "yelp-other.hook")) as f:
                print("Pattern: %s/yelp/other-${id}.txt" % self.temp_dir,
                      file=f)
                print("Hook-Name: yelp", file=f)
            os.mkdir(os.path.join(self.temp_dir, "unity"))
            unity_path = os.path.join(
                self.temp_dir, "unity", "test_app_1.0.scope")
            os.symlink("dummy", unity_path)
            os.mkdir(os.path.join(self.temp_dir, "yelp"))
            yelp_docs_path = os.path.join(
                self.temp_dir, "yelp", "docs-test_app_1.0.txt")
            os.symlink("dummy", yelp_docs_path)
            yelp_other_path = os.path.join(
                self.temp_dir, "yelp", "other-test_app_1.0.txt")
            os.symlink("dummy", yelp_other_path)
            package_dir = os.path.join(self.temp_dir, "test")
            with mkfile(os.path.join(
                    package_dir, "1.0", ".click", "info",
                    "test.manifest")) as f:
                json.dump(
                    {"hooks": {
                        "app": {"yelp": "foo.txt", "unity": "foo.scope"}}
                    }, f)
            Click.package_remove_hooks(self.db, "test", "1.0", user_name=None)
            self.assertFalse(os.path.lexists(unity_path))
            self.assertFalse(os.path.lexists(yelp_docs_path))
            self.assertFalse(os.path.lexists(yelp_other_path))


class TestPackageHooksValidateFramework(TestClickHookBase):

    def _setup_test_env(self, preloads):
        preloads["click_get_user_home"].return_value = b"/home/test-user"
        self._setup_hooks_dir(
            preloads, os.path.join(self.temp_dir, "hooks"))
        self._make_hook_file(dedent("""\
                           User-Level: yes
                           Pattern: %s/${id}.test
        """) % self.temp_dir)
        self.hook_symlink_path = os.path.join(
            self.temp_dir, "test-1_test1-app_1.0.test")

    def test_links_are_kept_on_validate_framework(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                "click_get_frameworks_dir",
                ) as (enter, preloads):
            enter()
            self._setup_frameworks(
                preloads, frameworks=["ubuntu-sdk-13.10"])
            self._setup_test_env(preloads)
            self._make_installed_click(json_data={
                "framework": "ubuntu-sdk-13.10",
                "hooks": {
                    "test1-app": {"test": "target-1"}
                },
            })
            self.assertTrue(os.path.lexists(self.hook_symlink_path))
            # run the hooks
            Click.run_user_hooks(self.db, user_name=self.TEST_USER)
            self.assertTrue(os.path.lexists(self.hook_symlink_path))

    def test_links_are_kept_multiple_frameworks(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                "click_get_frameworks_dir",
                ) as (enter, preloads):
            enter()
            self._setup_frameworks(
                preloads, frameworks=["ubuntu-sdk-14.04", "ubuntu-sdk-13.10"])
            self._setup_test_env(preloads)
            self._make_installed_click(json_data={
                "framework": "ubuntu-sdk-13.10",
                "hooks": {
                    "test1-app": {"test": "target-1"}
                },
            })
            self.assertTrue(os.path.lexists(self.hook_symlink_path))
            # run the hooks
            Click.run_user_hooks(self.db, user_name=self.TEST_USER)
            self.assertTrue(os.path.lexists(self.hook_symlink_path))

    def test_links_are_removed_on_missing_framework(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                "click_get_frameworks_dir",
                ) as (enter, preloads):
            enter()
            self._setup_frameworks(preloads, frameworks=["missing"])
            self._setup_test_env(preloads)
            self._make_installed_click(json_data={
                "framework": "ubuntu-sdk-13.10",
                "hooks": {
                    "test1-app": {"test": "target-1"}
                },
            })
            self.assertTrue(os.path.lexists(self.hook_symlink_path))
            # run the hooks
            Click.run_user_hooks(self.db, user_name=self.TEST_USER)
            self.assertFalse(os.path.lexists(self.hook_symlink_path))

    def test_links_are_removed_on_missing_multiple_framework(self):
        with self.run_in_subprocess(
                "click_get_hooks_dir", "click_get_user_home",
                "click_get_frameworks_dir",
                ) as (enter, preloads):
            enter()
            self._setup_frameworks(preloads, frameworks=["ubuntu-sdk-13.10"])
            self._setup_test_env(preloads)
            self._make_installed_click(json_data={
                "framework": "ubuntu-sdk-13.10, ubuntu-sdk-13.10-html",
                "hooks": {
                    "test1-app": {"test": "target-1"}
                },
            })
            self.assertTrue(os.path.lexists(self.hook_symlink_path))
            # run the hooks
            Click.run_user_hooks(self.db, user_name=self.TEST_USER)
            self.assertFalse(os.path.lexists(self.hook_symlink_path))
