check_SCRIPTS = \
	test-runner.sh \
	test-fixure-wrapper.sh \
	install-click.sh \
	install-click-not-exists.sh \
	install-click-no-perms.sh \
	remove-click.sh \
	remove-click-preinstalled.sh \
	remove-click-not-installed.sh

EXTRA_DIST = $(check_SCRIPTS)

TESTS = \
	install-click.sh \
	install-click-not-exists.sh \
	install-click-no-perms.sh \
	remove-click.sh \
	remove-click-preinstalled.sh \
	remove-click-not-installed.sh

TEST_EXTENSIONS = .sh
SH_LOG_COMPILER = $(SHELL) test-runner.sh
