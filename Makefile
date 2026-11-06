.DEFAULT_GOAL := all
HOST_OS := $(shell uname -s 2>/dev/null)
ifeq ($(OS),Windows_NT)
HOST_GUI_TARGET := windows-gui-package
else ifeq ($(HOST_OS),Darwin)
HOST_GUI_TARGET := macos-app
else ifeq ($(HOST_OS),Linux)
HOST_GUI_TARGET := linux-gui-package
endif
CC ?= cc
ifeq ($(origin CC),default)
ifneq ($(wildcard /opt/homebrew/opt/llvm/bin/clang),)
CC := /opt/homebrew/opt/llvm/bin/clang
endif
endif
AR = ar
MODE ?= release
XF_ROOT ?= ../XF
LS_ROOT ?= $(XF_ROOT)/vendor/lambdaScript
BUILD := build/$(MODE)
ifeq ($(MODE),release)
BIN := bin/cats
else
BIN := bin/$(MODE)/cats
endif
WARN := -std=c11 -Wall -Wextra -Wpedantic
ifeq ($(MODE),release)
MODE_FLAGS := -O2
else ifeq ($(MODE),asan)
MODE_FLAGS := -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined
else ifeq ($(MODE),fuzz)
MODE_FLAGS := -O1 -g -fno-omit-frame-pointer -fsanitize=fuzzer-no-link,address,undefined
else ifeq ($(MODE),lsan)
MODE_FLAGS := -O1 -g -fno-omit-frame-pointer -fsanitize=leak
else ifeq ($(MODE),tsan)
MODE_FLAGS := -O1 -g -fno-omit-frame-pointer -fsanitize=thread
else
$(error Unsupported MODE: $(MODE))
endif
XF_NAMES := ast interp lexer parser symTable value vm gc mt core simd
CORE_NAMES := helpers math str os generics regex format ds edit process img lambda
LS_NAMES := ast err interp lexer ls parser symTable value
XF_SRCS := $(addprefix $(XF_ROOT)/src/,$(addsuffix .c,$(XF_NAMES))) \
 $(addprefix $(XF_ROOT)/src/core/,$(addsuffix .c,$(CORE_NAMES))) \
 $(XF_ROOT)/lib/driver.c $(XF_ROOT)/lib/api.c
XF_OBJS := $(addprefix $(BUILD)/xf/,$(XF_SRCS:$(XF_ROOT)/%.c=%.o))
LS_OBJS := $(addprefix $(BUILD)/ls/,$(addsuffix .o,$(LS_NAMES)))
CPPFLAGS += -D_FILE_OFFSET_BITS=64 -Iinclude -I$(XF_ROOT)/lib -I$(BUILD) -Isrc
CPPFLAGS += -I$(XF_ROOT)/public -I$(LS_ROOT)/include
ifeq ($(WINDOWS_TARGET),1)
override CPPFLAGS += -D_WIN32_WINNT=0x0601
override LDLIBS += -lntdll -lbcrypt
WINDOWS_FS_OBJ := $(BUILD)/cat/win_fs.o
$(BUILD)/cat/win_fs.o: src/win_fs.c src/win_fs.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
endif
ifeq ($(WINDOWS_TARGET),1)
CATS_PROGRAM := $(BUILD)/cats.exe
else
CATS_PROGRAM := $(BUILD)/cats
endif
CFLAGS += $(WARN) $(MODE_FLAGS) -MMD -MP
LDLIBS += -lm -lpthread
ZLIB_LIBS ?= -lz

$(BUILD)/xf/%.o: $(XF_ROOT)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/ls/%.o: $(LS_ROOT)/src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/smoke.o: tests/xf_smoke.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/libxf.a: $(XF_OBJS)
	$(AR) rcs $@ $^
$(BUILD)/libls.a: $(LS_OBJS)
	$(AR) rcs $@ $^
$(BUILD)/libcats-transform.a: $(BUILD)/cat/transform.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(AR) rcs $@ $(BUILD)/cat/transform.o
transform-library: $(BUILD)/libcats-transform.a
$(BUILD)/libcats-support.a: $(BUILD)/cat/io.o $(BUILD)/cat/sha256.o $(BUILD)/cat/gzip.o
	$(AR) rcs $@ $^
support-library: $(BUILD)/libcats-support.a
.PHONY: transform-library support-library
$(BUILD)/xf-smoke: $(BUILD)/smoke.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS)
all: $(BUILD)/xf-smoke
all: $(HOST_GUI_TARGET)
test: all transform-test integration-test
	UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 $(BUILD)/xf-smoke > $(BUILD)/smoke.out
	cmp tests/xf_smoke.expected $(BUILD)/smoke.out
	@cat $(BUILD)/smoke.out
asan tsan lsan:
	$(MAKE) MODE=$@ test
clean:
	rm -rf build bin/cats bin/catc bin/linux-x64 bin/asan bin/tsan bin/lsan
-include $(XF_OBJS:.o=.d) $(LS_OBJS:.o=.d) $(BUILD)/smoke.d
.PHONY: all test asan tsan lsan clean

$(BUILD)/table_source.h: lib/Table.xf tools/embed.py
	@mkdir -p $(dir $@)
	python3 tools/embed.py $< $@
$(BUILD)/cat/%.o: src/%.c $(BUILD)/table_source.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/transform-test.o: tests/transform_test.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/transform-test: $(BUILD)/transform-test.o $(BUILD)/cat/transform.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS)
transform-test: $(BUILD)/transform-test
	UBSAN_OPTIONS=halt_on_error=1 $(BUILD)/transform-test
-include $(wildcard $(BUILD)/cat/*.d) $(BUILD)/transform-test.d

$(CATS_PROGRAM): $(BUILD)/cat/catc.o $(BUILD)/cat/transform.o $(BUILD)/cat/sha256.o $(BUILD)/cat/gzip.o $(BUILD)/cat/io.o $(WINDOWS_FS_OBJ) $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS) $(ZLIB_LIBS)
ifneq ($(abspath $(BIN)),$(abspath $(CATS_PROGRAM)))
$(BIN): $(CATS_PROGRAM)
	@mkdir -p $(dir $@)
	cp $< $@
	chmod +x $@
endif

$(BUILD)/catc: $(CATS_PROGRAM)
	ln -sfn cats $@

# Preserve the old command name for existing project integrations.
ifeq ($(MODE),release)
CATC_ALIAS := bin/catc
else
CATC_ALIAS := bin/$(MODE)/catc
endif
$(CATC_ALIAS): $(BIN)
	ln -sfn cats $@
all: $(CATC_ALIAS)
all: $(BIN)

integration-test: $(CATS_PROGRAM)
	python3 tests/integration.py $(CATS_PROGRAM)
.PHONY: transform-test integration-test

$(BUILD)/cat/catc-testing.o: src/catc.c $(BUILD)/table_source.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -DCAT_TESTING -c $< -o $@
$(BUILD)/cat/io-testing.o: src/io.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -DCAT_TESTING -c $< -o $@
$(BUILD)/catc-testing: $(BUILD)/cat/catc-testing.o $(BUILD)/cat/io-testing.o $(BUILD)/cat/transform.o $(BUILD)/cat/sha256.o $(BUILD)/cat/gzip.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS) $(ZLIB_LIBS)
failure-test: $(BUILD)/catc-testing $(BUILD)/cats $(BUILD)/catc
	python3 tests/failures.py $(BUILD)/catc-testing $(BUILD)/catc
compatibility-test: $(BUILD)/cats
	python3 tests/compatibility.py $(BUILD)/cats
test: failure-test compatibility-test
.PHONY: failure-test compatibility-test

FUZZ_SECONDS ?= 60
FUZZ_CC ?= $(if $(wildcard /opt/homebrew/opt/llvm/bin/clang),/opt/homebrew/opt/llvm/bin/clang,clang)
FUZZ_BUILD ?= build/fuzz-llvm
$(BUILD)/cat/catc-fuzz.o: src/catc.c $(BUILD)/table_source.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -DCAT_FUZZING -c $< -o $@
$(BUILD)/archive-fuzz.o: tests/archive_fuzz.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/tree-fuzz.o: tests/tree_fuzz.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/archive-fuzz: $(BUILD)/archive-fuzz.o $(BUILD)/cat/catc-fuzz.o $(BUILD)/cat/io.o $(BUILD)/cat/transform.o $(BUILD)/cat/sha256.o $(BUILD)/cat/gzip.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) -fsanitize=fuzzer -o $@ $^ $(LDLIBS) $(ZLIB_LIBS)
$(BUILD)/tree-fuzz: $(BUILD)/tree-fuzz.o $(BUILD)/cat/transform.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) -fsanitize=fuzzer -o $@ $^ $(LDLIBS)
fuzz-build: $(BUILD)/archive-fuzz $(BUILD)/tree-fuzz
fuzz:
	$(MAKE) MODE=fuzz CC=$(FUZZ_CC) BUILD=$(FUZZ_BUILD) fuzz-build
	python3 tools/seed_fuzz.py $(FUZZ_BUILD)
	python3 tools/fuzz.py $(FUZZ_BUILD)/archive-fuzz $(FUZZ_BUILD)/archive-corpus --seconds $(FUZZ_SECONDS)
	python3 tools/fuzz.py $(FUZZ_BUILD)/tree-fuzz $(FUZZ_BUILD)/tree-corpus --seconds $(FUZZ_SECONDS)
.PHONY: fuzz fuzz-build
streaming-test: $(BUILD)/cats
	python3 tests/streaming.py $(BUILD)/cats
.PHONY: streaming-test
PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
DATADIR ?= $(PREFIX)/share
INCLUDEDIR ?= $(PREFIX)/include
LIBDIR ?= $(PREFIX)/lib
CATS_LIBDIR ?= $(LIBDIR)/cats
PKGCONFIGDIR ?= $(LIBDIR)/pkgconfig
DESTDIR ?=
install: $(BIN) $(BUILD)/libcats-transform.a $(BUILD)/libcats-support.a
	install -d $(DESTDIR)$(BINDIR) $(DESTDIR)$(DATADIR)/doc/cats $(DESTDIR)$(INCLUDEDIR)/cats $(DESTDIR)$(CATS_LIBDIR) $(DESTDIR)$(PKGCONFIGDIR)
	install -m 755 $(BIN) $(DESTDIR)$(BINDIR)/cats
	ln -sfn cats $(DESTDIR)$(BINDIR)/catc
	install -m 644 include/cats/transform.h include/cats/support.h $(DESTDIR)$(INCLUDEDIR)/cats/
	install -m 644 $(BUILD)/libcats-transform.a $(BUILD)/libcats-support.a $(BUILD)/libxf.a $(BUILD)/libls.a $(DESTDIR)$(CATS_LIBDIR)/
	for pc in cats-transform cats-support; do \
		sed -e 's|@prefix@|$(PREFIX)|g' -e 's|@includedir@|$(INCLUDEDIR)|g' -e 's|@cats_libdir@|$(CATS_LIBDIR)|g' \
			packaging/$$pc.pc.in > $(DESTDIR)$(PKGCONFIGDIR)/$$pc.pc || exit $$?; \
	done
	install -m 644 LICENSE THIRD_PARTY.md README.md docs/FORMAT-v0.1.md docs/FORMAT-v0.7.md docs/FORMAT-v0.8.md \
		docs/CLI-INTEGRATION.md $(DESTDIR)$(DATADIR)/doc/cats/
	install -d $(DESTDIR)$(DATADIR)/doc/cats/licenses
	install -m 644 $(filter-out licenses/._%,$(wildcard licenses/*.txt)) $(DESTDIR)$(DATADIR)/doc/cats/licenses/
.PHONY: install
dependency-check: $(BIN)
	python3 tools/check_project_catc.py $(if $(strip $(CATS)),--cats "$(CATS)",$(if $(strip $(CATC)),--cats "$(CATC)",)) --reference-cats "$(BIN)"
.PHONY: dependency-check
package: $(BIN)
	python3 tools/package.py binary --binary $(BIN) --output releases/cats-binary.tar.gz
gui-source-check:
	python3 -m py_compile gui/cat_gui.py gui/cat_archive.py
macos-app: $(BIN) gui-source-check
	python3 tools/macos_app.py --binary $(BIN) --output $(BUILD)/macos/CAT.app
macos-app-test: $(BIN)
	python3 tests/macos_app.py $(BIN)
gui:
	python3 gui/cat_gui.py
gui-test: $(BIN)
	python3 tests/gui_archive.py $(BIN)
gui-portable-test:
	python3 tests/gui_archive_portable.py
gui-fixture-smoke:
	python3 tests/gui_fixture_smoke.py
source-package:
	python3 tools/package.py source --output releases/cats-source.tar.gz
WINDOWS_GUI_PACKAGE ?= releases/cats-gui-windows.zip
windows-gui-package: gui-source-check
	python3 tools/package_windows_gui.py --output $(WINDOWS_GUI_PACKAGE)
LINUX_GUI_PACKAGE ?= releases/cats-gui-linux.tar.gz
linux-gui-package: gui-source-check
	python3 tools/package_linux_gui.py --output $(LINUX_GUI_PACKAGE)
.PHONY: install package macos-app macos-app-test gui gui-test gui-portable-test gui-fixture-smoke gui-source-check source-package windows-gui-package linux-gui-package

# Optional cross build for a Linux x86_64 GNU toolchain. Supply a matching
# static zlib build (the zlib headers and libz.a must target x86_64 Linux).
LINUX_X64_CC ?= $(shell command -v x86_64-unknown-linux-gnu-gcc 2>/dev/null)
LINUX_X64_AR ?= $(shell command -v x86_64-unknown-linux-gnu-ar 2>/dev/null)
LINUX_X64_ZLIB_ROOT ?=
LINUX_X64_BUILD ?= build/linux-x64
LINUX_X64_BIN ?= bin/linux-x64/cats
linux-x64-cross:
	@test -n "$(LINUX_X64_CC)" || { echo 'set LINUX_X64_CC to an x86_64 Linux GCC cross compiler' >&2; exit 2; }
	@test -n "$(LINUX_X64_AR)" || { echo 'set LINUX_X64_AR to the matching x86_64 Linux ar' >&2; exit 2; }
	@test -f "$(LINUX_X64_ZLIB_ROOT)/zlib.h" || { echo 'set LINUX_X64_ZLIB_ROOT to a matching Linux zlib build root' >&2; exit 2; }
	@test -f "$(LINUX_X64_ZLIB_ROOT)/libz.a" || { echo 'matching static libz.a is required in LINUX_X64_ZLIB_ROOT' >&2; exit 2; }
	$(MAKE) MODE=release BUILD=$(LINUX_X64_BUILD) BIN=$(LINUX_X64_BIN) \
		CC='$(LINUX_X64_CC)' AR='$(LINUX_X64_AR)' \
		CPPFLAGS='-D_FILE_OFFSET_BITS=64 -Iinclude -I$(XF_ROOT)/lib -I$(LINUX_X64_BUILD) -Isrc -I$(XF_ROOT)/public -I$(LS_ROOT)/include -I$(LINUX_X64_ZLIB_ROOT)' \
		ZLIB_LIBS='$(LINUX_X64_ZLIB_ROOT)/libz.a' LDLIBS='-lm -lpthread' $(LINUX_X64_BIN)
.PHONY: linux-x64-cross

# Homebrew MinGW-w64 x86_64 Windows CLI cross-build. PCRE2 must be built for
# Windows with its POSIX wrapper; native Homebrew PCRE2 archives are not usable.
WINDOWS_X64_CC ?= $(shell command -v x86_64-w64-mingw32-gcc 2>/dev/null)
WINDOWS_X64_AR ?= $(shell command -v x86_64-w64-mingw32-ar 2>/dev/null)
WINDOWS_X64_ZLIB_ROOT ?=
WINDOWS_X64_PCRE2_INCLUDE ?=
WINDOWS_X64_PCRE2_LIBDIR ?=
WINDOWS_X64_BUILD ?= build/windows-x64
WINDOWS_X64_BIN ?= bin/windows-x64/cats.exe
windows-x64-cross:
	@test -n "$(WINDOWS_X64_CC)" || { echo 'set WINDOWS_X64_CC to the Homebrew MinGW-w64 compiler' >&2; exit 2; }
	@test -n "$(WINDOWS_X64_AR)" || { echo 'set WINDOWS_X64_AR to the matching MinGW-w64 archiver' >&2; exit 2; }
	@test -f "$(WINDOWS_X64_ZLIB_ROOT)/zlib.h" || { echo 'set WINDOWS_X64_ZLIB_ROOT to a Windows-target zlib build root' >&2; exit 2; }
	@test -f "$(WINDOWS_X64_ZLIB_ROOT)/libz.a" || { echo 'Windows-target static libz.a is required' >&2; exit 2; }
	@test -f "$(WINDOWS_X64_PCRE2_INCLUDE)/pcre2posix.h" || { echo 'set WINDOWS_X64_PCRE2_INCLUDE to the Windows PCRE2 interface headers' >&2; exit 2; }
	@test -f "$(WINDOWS_X64_PCRE2_LIBDIR)/libpcre2-posix.a" || { echo 'Windows-target libpcre2-posix.a is required' >&2; exit 2; }
	@test -f "$(WINDOWS_X64_PCRE2_LIBDIR)/libpcre2-8.a" || { echo 'Windows-target libpcre2-8.a is required' >&2; exit 2; }
	$(MAKE) MODE=release WINDOWS_TARGET=1 BUILD=$(WINDOWS_X64_BUILD) BIN=$(WINDOWS_X64_BIN) \
		CC='$(WINDOWS_X64_CC)' AR='$(WINDOWS_X64_AR)' \
		CPPFLAGS='-D_FILE_OFFSET_BITS=64 -DXF_USE_PCRE2_POSIX -I$(WINDOWS_X64_PCRE2_INCLUDE) -I$(WINDOWS_X64_ZLIB_ROOT) -Iinclude -I$(XF_ROOT)/lib -I$(WINDOWS_X64_BUILD) -Isrc -I$(XF_ROOT)/public -I$(LS_ROOT)/include' \
		CFLAGS='-std=c11 -Wall -Wextra -Wpedantic -O2 -MMD -MP' LDFLAGS=-static \
		LDLIBS='-lm -lpthread -L$(WINDOWS_X64_PCRE2_LIBDIR) -lpcre2-posix -lpcre2-8' \
		ZLIB_LIBS='$(WINDOWS_X64_ZLIB_ROOT)/libz.a' $(WINDOWS_X64_BUILD)/cats.exe
	@mkdir -p $(dir $(WINDOWS_X64_BIN))
	cp $(WINDOWS_X64_BUILD)/cats.exe $(WINDOWS_X64_BIN)
.PHONY: windows-x64-cross

github-release-assets: macos-app source-package linux-gui-package windows-gui-package
	python3 tools/stage_github_release.py
.PHONY: github-release-assets
release-check:
	python3 tools/release_check.py
.PHONY: release-check
$(BUILD)/sha256-test: tests/sha256_test.c $(BUILD)/cat/sha256.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $(MODE_FLAGS) -o $@ $^ $(LDFLAGS)
sha256-test: $(BUILD)/sha256-test
	$(BUILD)/sha256-test
test: sha256-test
test: gui-test gui-portable-test
.PHONY: sha256-test
packaging-test: $(BUILD)/cats
	python3 tests/packaging.py $(BUILD)/cats
.PHONY: packaging-test
$(BUILD)/memory-test: tests/memory_test.c $(BUILD)/cat/catc-fuzz.o $(BUILD)/cat/io.o $(BUILD)/cat/transform.o $(BUILD)/cat/sha256.o $(BUILD)/cat/gzip.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(MODE_FLAGS) -o $@ $^ $(LDFLAGS) $(LDLIBS) $(ZLIB_LIBS)
leak-test: $(BUILD)/memory-test $(BUILD)/transform-test $(BUILD)/cats $(BUILD)/catc-testing
	$(BUILD)/transform-test
	$(BUILD)/memory-test tests/golden/v01.cat tests/golden/v01.cat.gz
	python3 tests/leak_cli.py $(BUILD)/cats $(BUILD)/catc-testing
.PHONY: leak-test

leak-cli-test: $(BUILD)/cats $(BUILD)/catc-testing
	python3 tests/leak_cli.py $(BUILD)/cats $(BUILD)/catc-testing
.PHONY: leak-cli-test
