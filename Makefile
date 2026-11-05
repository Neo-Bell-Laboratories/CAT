.DEFAULT_GOAL := all
CC ?= cc
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
CPPFLAGS += -D_FILE_OFFSET_BITS=64 -I$(XF_ROOT)/lib -I$(BUILD) -Isrc
CPPFLAGS += -I$(XF_ROOT)/public -I$(LS_ROOT)/include
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
$(BUILD)/xf-smoke: $(BUILD)/smoke.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS)
all: $(BUILD)/xf-smoke
test: all transform-test integration-test
	UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 $(BUILD)/xf-smoke > $(BUILD)/smoke.out
	cmp tests/xf_smoke.expected $(BUILD)/smoke.out
	@cat $(BUILD)/smoke.out
asan tsan lsan:
	$(MAKE) MODE=$@ test
clean:
	rm -rf build bin/cats bin/catc bin/asan bin/tsan bin/lsan
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

$(BUILD)/cats: $(BUILD)/cat/catc.o $(BUILD)/cat/transform.o $(BUILD)/cat/sha256.o $(BUILD)/cat/gzip.o $(BUILD)/cat/io.o $(BUILD)/libxf.a $(BUILD)/libls.a
	$(CC) $(MODE_FLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS) $(ZLIB_LIBS)
$(BIN): $(BUILD)/cats
	@mkdir -p $(dir $@)
	cp $< $@
	chmod +x $@

$(BUILD)/catc: $(BUILD)/cats
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

integration-test: $(BUILD)/cats
	python3 tests/integration.py $(BUILD)/cats
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
DESTDIR ?=
install: $(BIN)
	install -d $(DESTDIR)$(PREFIX)/bin $(DESTDIR)$(PREFIX)/share/doc/cats
	install -m 755 $(BIN) $(DESTDIR)$(PREFIX)/bin/cats
	ln -sfn cats $(DESTDIR)$(PREFIX)/bin/catc
	install -m 644 LICENSE THIRD_PARTY.md README.md docs/FORMAT-v0.1.md docs/FORMAT-v0.7.md docs/FORMAT-v0.8.md \
		docs/CLI-INTEGRATION.md $(DESTDIR)$(PREFIX)/share/doc/cats/
	install -d $(DESTDIR)$(PREFIX)/share/doc/cats/licenses
	install -m 644 $(filter-out licenses/._%,$(wildcard licenses/*.txt)) $(DESTDIR)$(PREFIX)/share/doc/cats/licenses/
.PHONY: install
CATS ?= cats
dependency-check: $(BIN)
	python3 tools/check_project_catc.py --cats "$(if $(CATC),$(CATC),$(CATS))" --reference-cats "$(BIN)"
.PHONY: dependency-check
package: $(BIN)
	python3 tools/package.py binary --binary $(BIN) --output releases/cats-development-binary.tar.gz
macos-app: $(BIN)
	python3 tools/macos_app.py --binary $(BIN) --output $(BUILD)/macos/CAT.app
macos-app-test: $(BIN)
	python3 tests/macos_app.py $(BIN)
gui:
	python3 gui/cat_gui.py
gui-test: $(BIN)
	python3 tests/gui_archive.py $(BIN)
source-package:
	python3 tools/package.py source --output releases/cats-development-source.tar.gz
WINDOWS_GUI_PACKAGE ?= releases/cats-gui-windows.zip
windows-gui-package:
	python3 tools/package_windows_gui.py --output $(WINDOWS_GUI_PACKAGE)
.PHONY: install package macos-app macos-app-test gui gui-test source-package windows-gui-package
release-check:
	python3 tools/release_check.py
.PHONY: release-check
$(BUILD)/sha256-test: tests/sha256_test.c $(BUILD)/cat/sha256.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $(MODE_FLAGS) -o $@ $^ $(LDFLAGS)
sha256-test: $(BUILD)/sha256-test
	$(BUILD)/sha256-test
test: sha256-test
test: gui-test
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
