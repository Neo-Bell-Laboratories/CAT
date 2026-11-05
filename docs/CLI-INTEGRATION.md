# CATS CLI integration

CATS is the Compression Aggregate Tree System. Its primary shared executable is
`cats`. The former `catc` command remains a compatibility alias; peer projects
can migrate at their own pace. Build integrations should invoke the executable
from `PATH` or accept a configurable path.

The current peer set is:

| Project | CATS role |
| --- | --- |
| `CAAT` | Uses the CATS byte transform while writing its separate audio format |
| `CEP` | CLI consumer |
| `CIT` | CLI consumer |
| `CITP` | CLI consumer |
| `CVCS` | CLI consumer |
| `css` | CLI consumer |
| `ssqlite` | CLI consumer |

There are seven peer projects in this list. CATS itself provides `cats`; it is
not a consumer. `comp` is intentionally excluded.

CAAT currently builds against CAT's internal transform objects so it can apply
the byte codec inside CAAT blocks. Its existing block format cannot be replaced
with whole-file `cats` calls without changing CAAT's format and streaming model.
The other projects use the shared CLI boundary when they add CATS workflows.

## Install and check

Build and install one shared copy:

```sh
make -C /Volumes/Projects/CAT
sudo make -C /Volumes/Projects/CAT install PREFIX=/usr/local
cats --version
make -C /Volumes/Projects/CAT dependency-check
```

`make install` places `/usr/local/bin/cats` and a compatibility symlink at
`/usr/local/bin/catc`. Format, license, and project documentation goes under
`/usr/local/share/doc/cats`. `DESTDIR` supports staged installs for packages and
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

For a project operation, pass paths as separate process arguments; do not build
a shell command by concatenating filenames. For example, a backup command can run
`$(CATS) -eg INPUT --output OUTPUT.cat.gz`. Use `-v` to validate an archive,
`-i` for a human-readable listing, and `-d ARCHIVE DESTINATION` to extract.
CATS refuses to overwrite existing archive and extraction destinations. Check
the process exit status; successful encode, verify, inspect, or extraction exits
zero. The listing text is for display and is not a versioned machine-readable
API.

Default format v0.7 and compact format v0.8 archives support multiple top-level
inputs. Use `-ec` or `-ecg` to write v0.8, and `-dc` to extract it. Inspect and
verify identify both formats from their headers. Existing format versions remain
readable by the CATS CLI. Gzip-wrapped archives are auto-detected during decode.
