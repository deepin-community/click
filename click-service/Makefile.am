SUBDIRS = tests

pkglibexec_PROGRAMS = click-service

noinst_LTLIBRARIES = libclickservice.la

AM_CFLAGS = \
	$(LIBCLICK_CFLAGS) \
	$(SERVICE_CFLAGS) \
	$(COVERAGE_CFLAGS) \
	-I$(top_builddir)/lib/click
	-Wall \
	-Wextra

libclickservice_la_SOURCES = \
	cs-click-gdbus-generated.c \
	cs-click-gdbus-generated.h

libclickservice_la_LIBADD = \
	$(SERVICE_LIBS)

libclickservice_la_LDFLAGS = \
	$(COVERAGE_LDFLAGS) \
	-avoid-version \
	-static

click_service_SOURCES = \
	main.c

click_service_CPPFLAGS = \
	-DG_LOG_DOMAIN=\"click-service\"

click_service_LDFLAGS = \
	$(COVERAGE_LDFLAGS)

click_service_LDADD = \
	$(SERVICE_LIBS) \
	../lib/click/libclick-0.4.la \
	libclickservice.la

dbuspolicydir = $(sysconfdir)/dbus-1/system.d
dbuspolicy_DATA = com.lomiri.click.conf

dbusservicedir = $(datadir)/dbus-1/system-services
dbusservice_DATA = com.lomiri.click.service

%.service: %.service.in
	sed -e "s,[@]pkglibexecdir[@],$(pkglibexecdir),g" $< > $@

EXTRA_DIST = \
	$(dbuspolicy_DATA) \
	$(dbusservice_DATA).in

MAINTAINERCLEANFILES = \
	Makefile.in

main.c: cs-click-gdbus-generated.h

cs-click-gdbus-generated.c cs-click-gdbus-generated.h: com.lomiri.click.xml
	gdbus-codegen --interface-prefix=com.lomiri. --c-namespace=CS --generate-c-code=cs-click-gdbus-generated com.lomiri.click.xml

CLEANFILES = \
	com.lomiri.click.service \
	cs-click-gdbus-generated.c \
	cs-click-gdbus-generated.h
