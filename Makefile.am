SUBDIRS = lib preload click_package conf debhelper init schroot click-service

ACLOCAL_AMFLAGS = -I m4

all-local:
	set -e; for python in $(PYTHON_INTERPRETERS); do \
		$$python setup.py build; \
	done

check-local:
	set -e; for python in $(PYTHON_INTERPRETERS); do \
		$$python setup.py test; \
	done

coverage-python.xml:
	$(MAKE) $(AM_MAKEFLAGS) check

# setuptools likes to leave some debris around, which confuses things.
install-exec-hook:
	find build -name \*.pyc -print0 | xargs -0r rm -f
	find build -name __pycache__ -print0 | xargs -0r rm -rf
	find build -name \*.egg-info -print0 | xargs -0r rm -rf
	set -e; for python in $(PYTHON_INTERPRETERS); do \
		$$python setup.py install $(PYTHON_INSTALL_FLAGS); \
	done

clean-local:
	rm -rf build *.egg-info .tox
	find -name \*.pyc -print0 | xargs -0r rm -f
	find -name __pycache__ -print0 | xargs -0r rm -rf
	rm -f .coverage coverage-python.xml

include $(top_srcdir)/Makefile.am.coverage
