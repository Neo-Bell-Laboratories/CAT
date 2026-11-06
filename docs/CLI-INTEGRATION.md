# CATS CLI integration

CATS is the Compression Aggregate Tree System. Its primary shared executable is
`cats`. The former `catc` command remains a compatibility alias; peer projects
can migrate at their own pace. Build integrations should invoke the executable
from `PATH` or accept a configurable path.

The current peer set is:

| Project | CATS role |
| --- | --- |
| `CAT` | Self-compatibility check for the CATS provider |
| `CEP` | CLI consumer |
| `CAAT` | Uses the CATS byte transform while writing its separate audio format |
| `CITP` | CLI consumer |
| `CVCS` | CLI consumer |
| `ssqlite` | CLI consumer |
| `CIT` | CLI consumer |
| `css` | CLI consumer |
| `kitty litter` | CLI compatibility target |

The checker validates the nine explicitly named directories, resolving names
case-insensitively. `CAT` is included as a self-compatibility check; `comp` and
`Cattery` are not in this peer set.

CAAT builds against CATS's supported transform and support libraries so it can
apply the byte codec inside CAAT blocks. Its existing block format cannot be
replaced with whole-file `cats` calls without changing CAAT's format and
streaming model. The other projects use the shared CLI boundary when they add
CATS workflows.

## Install and check

Build and install one shared copy:

```sh
make -C /Volumes/Projects/CAT
make -C /Volumes/Projects/CAT install PREFIX=/usr/local BINDIR=/usr/local/bin DATADIR="$HOME/.local/share"
cats --version
make -C /Volumes/Projects/CAT dependency-check
```

`make install` places `/usr/local/bin/cats` and a compatibility symlink at
`/usr/local/bin/catc`. Format, license, and project documentation goes under
`$(DATADIR)/doc/cats` (default `/usr/local/share/doc/cats`). `BINDIR` and
`DATADIR` can be set independently when the executable and shared documentation
have different permissions. `DESTDIR` supports staged installs for packages and
sysroots. On Linux, use the same `PREFIX` convention, commonly `/usr` for a
package-managed install.

Consumers can configure either command name. New integrations should prefer:

```make
CATS ?= cats

check-cats:
	@command -v "$(CATS)" >/dev/null || { echo "CATS not found: $(CATS)" >&2; exit 1; }
```

Older build files using `CATC ?= catc` continue to work. The CATC environment
variable and `--catc` option remain accepted by the dependency checker.

## Embedded block transform

Projects that need the aggregate-tree byte transform inside another container
format should link the supported C API instead of reaching into CAT's private
`src/` objects. `make install` installs `include/cats/transform.h`,
`include/cats/support.h`, static transform/support libraries, their XF and
LambdaScript dependencies, and `cats-transform.pc` / `cats-support.pc`. Build
an embedding project with:

```sh
cc $(pkg-config --cflags cats-transform cats-support) -o app app.c \
  $(pkg-config --static --libs cats-transform cats-support)
```

Call `cat_transform_init()` before use and `cat_transform_close()` when done.
The API is serialized and not thread-safe. Each block is limited to 8192 bytes;
the caller owns returned buffers and frees them with `free()`. See
`include/cats/transform.h` and `include/cats/support.h` for lifecycle and
version constants. CAAT builds against these public headers and static
libraries while retaining its audio container and streaming behavior. Its
Makefile supports the source-tree build by default and an installed-only build:

```sh
make -C /Volumes/Projects/CAAT CATS_PREFIX=/usr/local
```

For a staged installation, set `CATS_PREFIX` to the staged prefix and
`CATS_SYSROOT` to its `DESTDIR` root.

For a project operation, pass paths as separate process arguments; do not build
a shell command by concatenating filenames. For example, a backup command can run
`$(CATS) -eg INPUT --output OUTPUT.cat.gz`. Use `-v` to validate an archive,
`-i` for a human-readable listing, and `-d ARCHIVE DESTINATION` to extract.
CATS refuses to overwrite existing archive and extraction destinations. Check
the process exit status; successful encode, verify, inspect, or extraction exits
zero. The listing text is for display and is not a versioned machine-readable
API.
An extension-less output name gets `.cat`, or `.cat.gz` when `-g` is enabled.
Recognized `.cat` and `.cat.gz` suffixes are adjusted to match the `-g` setting;
other explicit suffixes are preserved.

Default format v0.7 and compact format v0.8 archives support multiple top-level
inputs. Use `-ec` or `-ecg` to write v0.8, and `-dc` to extract it. Inspect and
verify identify both formats from their headers. Existing format versions remain
readable by the CATS CLI. Gzip-wrapped archives are auto-detected during decode.

## GUI distribution

Build the standalone GUI packages with `make linux-gui-package` and
`make windows-gui-package`. The Linux tarball includes its per-user/system
installer, desktop/MIME integration, icons, and license notices. The Windows ZIP
includes its per-user installer and archive icon. Both GUI readers inspect and
extract archives without a CATS CLI executable. On macOS, `make macos-app` builds
the native CAT.app bundle.
