/*
 * Copyright (C) 2022 Guido Berhoerster <guido+ubports@berhoerster.name>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; version 3 of the License.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <pwd.h>
#include <stdint.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include <gio/gio.h>

#include "click.h"
#include "cs-click-gdbus-generated.h"

#ifndef DEFAULT_PATH
#define	DEFAULT_PATH	"/usr/sbin:/usr/bin:/sbin:/bin"
#endif /* !DEFAULT_PATH */

typedef enum {
	CS_CLICK_ERROR_INTERNAL_ERROR,
	CS_CLICK_ERROR_OPERATION_FAILED
} CSError;

#define	CS_CLICK_ERROR	(cs_click_error_quark())

static GMainLoop	*loop;

static gboolean	debug;
static gboolean	test_mode;
/* Used by tests. */
static gchar ** db_paths = NULL;

static const GOptionEntry entries[] = {
	{ "debug", 'v', 0, G_OPTION_ARG_NONE, &debug, "Enable debug logging",
	    NULL },
	{ NULL }
};

GQuark
cs_click_error_quark(void)
{
	static GQuark	quark;

	if (quark == 0) {
		quark = g_quark_from_static_string("cs-click-error-quark");

		g_dbus_error_register_error(quark,
		    CS_CLICK_ERROR_INTERNAL_ERROR,
		    "com.lomiri.click.InternalError");
		g_dbus_error_register_error(quark,
		    CS_CLICK_ERROR_OPERATION_FAILED,
		    "com.lomiri.click.OperationFailed");
	}
	return (quark);
}

static gboolean
get_dbus_credentials(GDBusMethodInvocation *invocation, uid_t *uidp,
    gid_t *gidp, gid_t *gidpp[], gsize *ngidp, char** namep, GError **error)
{
	GDBusConnection	*connection;
	const gchar	*sender;
	g_autoptr(GVariant) credentials = NULL;
	g_autoptr(GVariant) dict = NULL;
	guint32		uid;
	gsize		buf_max, buf_size, buf_size_new;
	g_autofree gchar *buf = NULL;
	struct passwd	passwd;
	struct passwd	*passwdp;
	gint		retval;
	g_autoptr(GVariant) gids_var = NULL;
	gsize		ngids = 0;
	const guint32	*gids = NULL;
	gsize		i;

	connection = g_dbus_method_invocation_get_connection(invocation);
	sender = g_dbus_method_invocation_get_sender(invocation);
	credentials = g_dbus_connection_call_sync(connection,
	    "org.freedesktop.DBus", "/org/freedesktop/DBus",
	    "org.freedesktop.DBus", "GetConnectionCredentials",
	    g_variant_new("(s)", sender), G_VARIANT_TYPE("(a{sv})"),
	    G_DBUS_CALL_FLAGS_NONE, G_MAXINT, NULL, error);
	if (credentials == NULL) {
		g_prefix_error(error,
		    "failed to get DBus sender credentials for %s:", sender);
		return (FALSE);
	}

	dict = g_variant_get_child_value(credentials, 0);
	if (!g_variant_lookup(dict, "UnixUserID", "u", &uid)) {
		g_set_error(error, CS_CLICK_ERROR,
		    CS_CLICK_ERROR_INTERNAL_ERROR,
		    "failed to get sender UID for %s", sender);
		return (FALSE);
	}

	/* obtain primary GID based on sender UID */
	buf_max = (size_t)sysconf(_SC_GETPW_R_SIZE_MAX);
	buf_size = (buf_max > 0) ? buf_max : 65535;
	buf = g_malloc(buf_size);
	while ((retval = getpwuid_r((uid_t)uid, &passwd, buf, buf_size,
	    &passwdp)) == ERANGE) {
		if (!g_size_checked_mul(&buf_size_new, buf_size, 2)) {
			break;
		}
		buf_size = buf_size_new;
		buf = g_realloc(buf, buf_size);
	}
	if (retval != 0) {
		g_set_error(error, CS_CLICK_ERROR,
		    CS_CLICK_ERROR_INTERNAL_ERROR,
		    "failed to get sender GID for %s", sender);
		return (FALSE);
	}

	/* this is optional */
	gids_var = g_variant_lookup_value(dict, "UnixGroupIDs",
	    G_VARIANT_TYPE_ARRAY);
	if (gids_var != NULL) {
		gids = g_variant_get_fixed_array(gids_var, &ngids,
		    sizeof (guint32));
	}

	if (uidp)
		*uidp = (uid_t)uid;
	if (gidp)
		*gidp = passwd.pw_gid;

	if (gidpp && ngidp) {
		*gidpp = NULL;
		if (ngids > 0) {
			*gidpp = g_new(gid_t, ngids);
			for (i = 0; i < ngids; i++) {
				(*gidpp)[i] = (gid_t)gids[i];
			}
		}
		*ngidp = ngids;
	}
	
	if (namep)
		*namep = g_strdup(passwd.pw_name);

	return (TRUE);
}

static int
open_unpriv(const gchar *path, int flags, mode_t mode, uid_t uid, gid_t gid,
    gid_t *gids, gsize ngids)
{
	int	saved_errno;
	uid_t	orig_uid;
	gid_t	orig_gid;
	g_autofree gid_t *orig_gids = NULL;
	gsize	orig_ngids;
	int	fd;

	if (test_mode) {
		fd = open(path, flags, mode);
		return (fd);
	}

	orig_uid = geteuid();
	orig_gid = getegid();
	orig_ngids = getgroups(0, NULL);
	orig_gids = g_new(gid_t, orig_ngids);
	if (getgroups(orig_ngids, orig_gids) < 0) {
		g_critical("getgroups: %s", g_strerror(errno));
		g_abort();
	}

	if (setgroups(ngids, gids) != 0) {
		g_critical("setgroups: %s", g_strerror(errno));
		g_abort();
	}
	if ((setegid(gid) != 0) || (getegid() != gid)) {
		g_critical("setegid failed");
		g_abort();
	}
	if ((seteuid(uid) != 0) || (geteuid() != uid)) {
		g_critical("seteuid failed");
		g_abort();
	}

	fd = open(path, flags, mode);
	saved_errno = errno;

	if (seteuid(orig_uid) != 0) {
		g_critical("seteuid: %s", g_strerror(errno));
		g_abort();
	}
	if (setegid(orig_gid) != 0) {
		g_critical("setegid: %s", g_strerror(errno));
		g_abort();
	}
	if (setgroups(orig_ngids, orig_gids)) {
		g_critical("setgroups: %s", g_strerror(errno));
		g_abort();
	}

	errno = saved_errno;
	return (fd);
}

static gboolean
on_handle_install(CSClick *click, GDBusMethodInvocation *invocation,
    gchar *path, G_GNUC_UNUSED gpointer user_data)
{
	uid_t		uid;
	gid_t		gid;
	g_autofree gid_t *gids = NULL;
	gsize		ngids;
	int		fd = -1;
	g_autofree gchar *proc_path = NULL;
	int			i;
	g_autofree gchar *root_arg = NULL;
	gchar		*argv[] = {
	    "click",
	    "install",
	    "--all-users",
	    "--allow-unauthenticated",
	    NULL,
	    NULL,
	    NULL
	};
	g_autofree gchar *output = NULL;
	gint		wstatus = 0;
	g_autoptr(GError) error = NULL;

	g_debug("package installation requested for %s", path);

	if (!get_dbus_credentials(invocation, &uid, &gid, &gids, &ngids,
	    /* namep */ NULL, &error)) {
		g_warning("failed to get sender credentials: %s",
		    error->message);
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "internal error");
		goto out;
	}

	/* open click package with the privileges of the sender */
	fd = open_unpriv(path, O_RDONLY, 0, uid, gid, gids, ngids);
	if (fd < 0) {
		g_debug("failed to open %s", g_strerror(errno));
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_OPERATION_FAILED,
		    "failed to open %s", path);
		goto out;
	}

	/* pass fd as procfs filename to click */
	proc_path = g_strdup_printf("/proc/%jd/fd/%d", (intmax_t)getpid(), fd);

	if (db_paths) {
		/* Get the last path in the path list. */
		for (i = 0; db_paths[i] != NULL; i++);
		i--;
		if (i >= 0)
			root_arg = g_strdup_printf("--root=%s", db_paths[i]);
	}
	/* TODO: maybe allow specifying root from DBus arguments? */

	if (root_arg) {
		argv[sizeof (argv) / sizeof (argv[0]) - 3] = root_arg;
		argv[sizeof (argv) / sizeof (argv[0]) - 2] = proc_path;
	} else {
		argv[sizeof (argv) / sizeof (argv[0]) - 3] = proc_path;
	}

	if (!g_spawn_sync("/", argv, NULL, G_SPAWN_SEARCH_PATH |
	    G_SPAWN_STDOUT_TO_DEV_NULL, NULL, NULL, NULL, &output, &wstatus,
	    &error)) {
		g_warning("failed to spawn click: %s", error->message);
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "failed to install %s due to internal error", path);
		goto out;
	}
	if (!WIFEXITED(wstatus)) {
		g_warning("click exited abnormally");
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "failed to install %s due to internal error", path);
		goto out;
	}
	g_debug("click exited with %d", WEXITSTATUS(wstatus));
	if (WEXITSTATUS(wstatus) != 0) {
		g_debug("click error: %s", output);
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR,
		    CS_CLICK_ERROR_OPERATION_FAILED,
		    "failed to install %s", path);
		goto out;
	}
	cs_click_complete_install(click, invocation);

out:
	if (fd >= 0) {
		close(fd);
	}

	return (TRUE);
}

static gboolean
on_handle_remove(CSClick *click, GDBusMethodInvocation *invocation,
    gchar *pkgid, G_GNUC_UNUSED gpointer user_data)
{
	int i;
	g_autofree gchar *user = NULL;

	g_autoptr(ClickDB) db = NULL;
	ClickSingleDB * overlay_db = NULL;
	g_autoptr(ClickUser) registry_user = NULL;
	g_autoptr(ClickUser) registry_all = NULL;

	g_autofree gchar * version_user = NULL;
	g_autofree gchar * version_all = NULL;

	g_autoptr(GError) error = NULL;
	g_autoptr(GError) error_all = NULL;

	gboolean did_uninstall = FALSE;

	if (!get_dbus_credentials(invocation, /* uidp */ NULL, /* gidp */ NULL,
		/* gidpp */ NULL, /* ngidp */ NULL, &user, &error)) {
		g_warning("Failed to get sender credentials: %s",
		    error->message);
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "internal error");
		return (TRUE);
	}

	db = click_db_new();
	click_db_read(db, /* db_dir */ NULL, &error);
	if (error) {
		g_warning("Failed to read Click DB: %s", error->message);
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "internal error");
		return (TRUE);
	}
	
	if (db_paths) {
		for (i = 0; db_paths[i] != NULL; i++)
			click_db_add(db, db_paths[i]);
	}
	/* TODO: maybe allow specifying root via DBus in the future? */

	if (click_db_get_size(db) <= 0) {
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "internal error");
		return (TRUE);
	}
	overlay_db = click_db_get(
	    db, click_db_get_size(db) - 1, /* error */ NULL);

	/*
	 * We perform removal on the registry that the package is actually
	 * installed. We try to avoid running removal of @all app on user registry,
	 * as otherwise the user registry will "hide" the app, and it'll get
	 * confusing.
	 */

	registry_all = click_user_new_for_all_users(db, &error);
	if (!registry_all) {
		g_warning("Failed to read @all Click DB: %s", error->message);
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "internal error");
		return (TRUE);
	}
	version_all =
		click_user_get_version(registry_all, pkgid, /* error */ NULL);

	g_debug("version_all: %s", version_all ?: "(NULL)");
	
	/*
	 * We don't want to actually remove (yet) if the app comes from an
	 * underlay. In case the app exists in user DB we don't want to hide
	 * it from here.
	 */
	if (version_all &&
	    click_single_db_has_package_version(
		overlay_db, pkgid, version_all))
	{
		click_user_remove(registry_all, pkgid, &error_all);
		click_db_maybe_remove(db, pkgid, version_all, /* error */ NULL);

		did_uninstall = TRUE;
	}

	/*
	 * Check for user registry after attempting to remove one from @all, since
	 * get_version() for the user will return a version from @all it none is in
	 * user registry. If, after we remove one from @all we still can query a
	 * version, then there's also one installed in user registry that we have to
	 * remove.
	 */

	registry_user = click_user_new_for_user(db, user, &error);
	if (!registry_user) {
		g_warning("Failed to read user Click DB: %s", error->message);
		g_dbus_method_invocation_return_error(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_INTERNAL_ERROR,
		    "internal error");
		return (TRUE);
	}
	version_user = click_user_get_version(registry_user, pkgid, &error);

	g_debug("version_user: %s", version_user ?: "(NULL)");

	if (!version_all && !version_user) {
		g_dbus_method_invocation_return_error_literal(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_OPERATION_FAILED,
		    error->message);
		return (TRUE);
	}

	/* Same goes for user registry. */
	if (version_user &&
	    click_single_db_has_package_version(
		overlay_db, pkgid, version_user))
	{
		click_user_remove(registry_user, pkgid, &error);
		click_db_maybe_remove(db, pkgid, version_user,
					/* error */ NULL);

		did_uninstall = TRUE;
	}

	/*
	 * Now, if the app actually doesn't exists in overlay DB for both @all
	 * and user registry, call click_user_remove(@all) to make it hidden.
	 */
	if (version_all && !did_uninstall) {
		click_user_remove(registry_all, pkgid, &error_all);
		/* Maybe unnecessary? */
		click_db_maybe_remove(db, pkgid, version_all, /* error */ NULL);
	}


	/* TODO: maybe remove data? */

	/*
	 * Now a tricky part: if we have package in both registries, we want to
	 * return the error only if both fails. But if only 1 exists, we want to
	 * return respective error. We take advantage that having error implies
	 * that the package exists.
	 */
	if ((error && error_all) ||
	    ((!version_user || !did_uninstall) && error_all) ||
	    (!version_all && error)) {
		g_dbus_method_invocation_return_error_literal(invocation,
		    CS_CLICK_ERROR, CS_CLICK_ERROR_OPERATION_FAILED,
		    (error ?: error_all)->message);
		return (TRUE);
	}

	cs_click_complete_remove(click, invocation);
	return (TRUE);
}

static void
on_bus_acquired(GDBusConnection *connection, const gchar *name,
    G_GNUC_UNUSED gpointer user_data)
{
	CSClick	*click;

	g_debug("acquired bus for name %s", name);

	click = cs_click_skeleton_new();

	g_signal_connect(G_OBJECT(click), "handle-install",
	    G_CALLBACK(on_handle_install), NULL);
	g_signal_connect(G_OBJECT(click), "handle-remove",
	    G_CALLBACK(on_handle_remove), NULL);

	if (!g_dbus_interface_skeleton_export(
	    G_DBUS_INTERFACE_SKELETON(click), connection,
	    "/com/lomiri/click", NULL)) {
		g_critical("failed to export interface");
		g_main_loop_quit(loop);
		return;
	}
}

static void
on_name_lost(GDBusConnection *connection, const gchar *name,
    G_GNUC_UNUSED gpointer user_data)
{
	if (connection == NULL) {
		g_warning("failed to connect to bus");
	} else {
		g_warning("lost name %s", name);
	}

	g_main_loop_quit(loop);
}

int
main(G_GNUC_UNUSED int argc, G_GNUC_UNUSED char *argv[])
{
	g_autofree gchar *messages_debug = NULL;
	guint		id;

	/*
	 * $PATH is not set when we are automatically started by system bus
	 * through dbus activation, which causes issues when click attemps to
	 * run the debsig-verify command, and when running dpkg to do the
	 * install. We don't want to override an already set $PATH though if
	 * one is set.
	 */
	g_setenv("PATH", DEFAULT_PATH, FALSE);
	g_debug("PATH is set to \"%s\"", g_getenv("PATH"));

	GError *error = NULL;
	GOptionContext *context;
	const gchar * db_paths_env;

	context = g_option_context_new(NULL);
	g_option_context_add_main_entries(context, entries, NULL);
	if(!g_option_context_parse(context, &argc, &argv, &error)) {
		g_printerr("option parsing failed: %s\n", error->message);
		exit(EXIT_FAILURE);
	}
	g_option_context_free(context);

	if (debug) {
		/* enable debug logging */
		messages_debug = g_strjoin(":", G_LOG_DOMAIN,
				g_getenv("G_MESSAGES_DEBUG"), NULL);
		g_setenv("G_MESSAGES_DEBUG", messages_debug, TRUE);
		g_free(messages_debug);
	}

	if (geteuid() != 0) {
		g_printerr("WARNING: running as unprivileged user, this "
		    "only works in a test environment\n");
		test_mode = TRUE;
	}

	db_paths_env = g_getenv("CLICK_SERVICE_TEST_DB_PATHS");
	if (db_paths_env)
		db_paths = g_strsplit(db_paths_env, ":", /* max_tokens = inf */ 0);

	loop = g_main_loop_new(NULL, FALSE);

	id = g_bus_own_name(G_BUS_TYPE_SYSTEM, "com.lomiri.click",
	    G_BUS_NAME_OWNER_FLAGS_NONE, on_bus_acquired, NULL,
	    on_name_lost, loop, NULL);

	g_main_loop_run(loop);

	g_bus_unown_name(id);
	g_clear_pointer(&loop, g_main_loop_unref);
	g_strfreev(db_paths);

	/* the main loop is only quit in case of errors */
	exit(EXIT_FAILURE);
}
