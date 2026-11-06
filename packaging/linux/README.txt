CATS GUI extractor for Linux

Requirements: Linux, Python 3 with Tk. Desktop file association also requires
shared-mime-info and a desktop environment.

1. Extract this archive.
2. Run `sh ./packaging/linux/install-gui.sh "$HOME/.local"` for a per-user
   install, or pass a system prefix such as `/usr/local` with appropriate write
   access.
3. Run `cats-gui ARCHIVE.cat` to inspect and extract an archive. The installer
   also installs the `cat-gui` compatibility name, desktop entry, MIME type,
   scalable icons, documentation, and license notices.

The .cat and .cat.gz reader is Python source and does not require the CATS CLI.
