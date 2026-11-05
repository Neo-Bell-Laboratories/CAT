"""Cross-platform CAT archive inspector and unarchiver."""
import os
from pathlib import Path
import queue
import sys
import threading
import unicodedata
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

from cat_archive import extract_archive, inspect_archive


def human_size(value):
    amount = float(value)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if amount < 1024 or unit == 'TB':
            return ('%d %s' % (amount, unit)) if unit == 'B' else ('%.1f %s' % (amount, unit))
        amount /= 1024


def safe_display_path(value):
    result = []
    for char in value:
        category = unicodedata.category(char)
        if category in ('Cc', 'Cf', 'Cs', 'Cn'):
            code = ord(char)
            result.append('\\x%02x' % code if code <= 0xff else '\\u%04x' % code)
        else:
            result.append(char)
    return ''.join(result)


def archive_folder_name(path):
    name = Path(path).name
    lower = name.lower()
    if lower.endswith('.cat.gz'):
        name = name[:-7]
    elif lower.endswith('.cat'):
        name = name[:-4]
    else:
        name = Path(name).stem
    return name or 'CATS Archive'


def available_folder_name(parent, preferred):
    if not os.path.lexists(os.path.join(parent, preferred)):
        return preferred
    candidate = preferred + '-extracted'
    suffix = 2
    while os.path.lexists(os.path.join(parent, candidate)):
        candidate = '%s-extracted-%d' % (preferred, suffix)
        suffix += 1
    return candidate


class CatWindow:
    def __init__(self, root, initial_archive=None):
        self.root = root
        self.events = queue.Queue()
        self.info = None
        self.busy = False
        self.generation = 0
        self.archive_var = tk.StringVar()
        self.parent_var = tk.StringVar()
        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value='Choose a CAT archive to inspect its contents.')
        self._style()
        self._layout()
        self.root.after(100, self._poll)
        if initial_archive:
            self.archive_var.set(os.path.abspath(initial_archive))
            self._set_destination(initial_archive)
            self.root.after(150, self.inspect)

    def _style(self):
        self.root.title('CATS Archive')
        self.root.geometry('900x650')
        self.root.minsize(700, 500)
        palette = {
            'background': '#f2f4f7',
            'foreground': '#18304d',
            'surface': '#ffffff',
            'muted': '#52677c',
            'accent': '#df8240',
            'selection': '#d7ece9',
        }
        for font_name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
            try:
                font = tkfont.nametofont(font_name)
                font.configure(size=11)
            except tk.TclError:
                pass
        style = ttk.Style(self.root)
        native_aqua = sys.platform == 'darwin' and 'aqua' in style.theme_names()
        if native_aqua:
            style.theme_use('aqua')
        elif 'clam' in style.theme_names():
            style.theme_use('clam')
        # Aqua draws using the user's current macOS appearance. Setting ttk
        # colors here overrides its dark-mode foreground without overriding
        # its native background, producing dark-on-dark invisible controls.
        if not native_aqua:
            self.root.configure(background=palette['background'])
            style.configure('TFrame', background=palette['background'])
            style.configure('TLabel', background=palette['background'],
                            foreground=palette['foreground'])
            style.configure('TLabelframe', background=palette['background'],
                            foreground=palette['foreground'])
            style.configure('TLabelframe.Label', background=palette['background'],
                            foreground=palette['foreground'])
            style.configure('TEntry', fieldbackground=palette['surface'],
                            foreground=palette['foreground'])
        style.configure('Header.TLabel', font=('TkDefaultFont', 20, 'bold'))
        style.configure('Subheader.TLabel', font=('TkDefaultFont', 11))
        if not native_aqua:
            style.configure('Subheader.TLabel', foreground=palette['muted'])
        style.configure('Primary.TButton', font=('TkDefaultFont', 11, 'bold'), padding=(16, 8))
        if native_aqua:
            style.configure('Treeview', rowheight=27)
        else:
            style.configure('Treeview', rowheight=27, background=palette['surface'],
                            fieldbackground=palette['surface'], foreground=palette['foreground'])
            style.map('Treeview', background=[('selected', palette['selection'])],
                      foreground=[('selected', palette['foreground'])])

    def _layout(self):
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill='both', expand=True)

        ttk.Label(outer, text='Unarchive CATS', style='Header.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Inspect and safely extract a CATS archive.',
                  style='Subheader.TLabel').pack(anchor='w', pady=(4, 20))

        ttk.Label(outer, text='Archive').pack(anchor='w')
        archive_row = ttk.Frame(outer)
        archive_row.pack(fill='x', pady=(5, 16))
        self.archive_entry = ttk.Entry(archive_row, textvariable=self.archive_var)
        self.archive_entry.pack(side='left', fill='x', expand=True)
        self.archive_browse = ttk.Button(archive_row, text='Browse…', command=self.choose_archive)
        self.archive_browse.pack(side='left', padx=(8, 0))
        self.inspect_button = ttk.Button(archive_row, text='Inspect', command=self.inspect)
        self.inspect_button.pack(side='left', padx=(8, 0))
        self.archive_entry.bind('<Return>', lambda _event: self.inspect())

        ttk.Label(outer, text='Extract into').pack(anchor='w')
        destination_row = ttk.Frame(outer)
        destination_row.pack(fill='x', pady=(5, 16))
        self.parent_entry = ttk.Entry(destination_row, textvariable=self.parent_var)
        self.parent_entry.pack(side='left', fill='x', expand=True)
        self.parent_browse = ttk.Button(destination_row, text='Choose location…', command=self.choose_parent)
        self.parent_browse.pack(side='left', padx=(8, 0))
        name_row = ttk.Frame(outer)
        name_row.pack(fill='x', pady=(0, 18))
        ttk.Label(name_row, text='New folder name').pack(side='left')
        self.folder_entry = ttk.Entry(name_row, textvariable=self.folder_var, width=34)
        self.folder_entry.pack(side='left', padx=(12, 0))

        content = ttk.LabelFrame(outer, text='Archive contents', padding=8)
        content.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(content, columns=('type', 'size', 'mode'), show='headings')
        self.tree.heading('type', text='Type')
        self.tree.heading('size', text='Size')
        self.tree.heading('mode', text='Mode')
        self.tree.column('#0', width=500, anchor='w')
        self.tree.column('type', width=90, anchor='w')
        self.tree.column('size', width=110, anchor='e')
        self.tree.column('mode', width=80, anchor='e')
        # The path is displayed as the implicit first column when show='tree headings'.
        self.tree.configure(show='tree headings')
        self.tree.heading('#0', text='Path', anchor='w')
        self.tree.column('#0', width=500, anchor='w')
        scrollbar = ttk.Scrollbar(content, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        footer = ttk.Frame(outer)
        footer.pack(fill='x', pady=(16, 0))
        self.status_label = ttk.Label(footer, textvariable=self.status_var)
        self.status_label.pack(side='left', fill='x', expand=True, anchor='w')
        self.progress = ttk.Progressbar(footer, mode='indeterminate', length=120)
        self.progress.pack(side='left', padx=12)
        self.extract_button = ttk.Button(footer, text='Extract', style='Primary.TButton',
                                         command=self.extract, state='disabled')
        self.extract_button.pack(side='right')

    def _set_destination(self, archive):
        path = Path(archive).absolute()
        self.parent_var.set(str(path.parent))
        preferred = archive_folder_name(path)
        self.folder_var.set(available_folder_name(str(path.parent), preferred))

    def choose_archive(self):
        if self.busy:
            return
        selected = filedialog.askopenfilename(
            parent=self.root, title='Choose a CAT archive',
            filetypes=[('CAT archives', '*.cat *.cat.gz'), ('All files', '*')])
        if selected:
            self.archive_var.set(selected)
            self._set_destination(selected)
            self.inspect()

    def choose_parent(self):
        if self.busy:
            return
        selected = filedialog.askdirectory(parent=self.root, title='Choose extraction location',
                                           mustexist=True)
        if selected:
            self.parent_var.set(selected)
            archive = self.archive_var.get().strip()
            if archive:
                self.folder_var.set(available_folder_name(
                    selected, archive_folder_name(archive)))

    def _set_busy(self, busy):
        self.busy = busy
        state = 'disabled' if busy else 'normal'
        for widget in (self.archive_entry, self.archive_browse, self.inspect_button,
                       self.parent_entry, self.parent_browse, self.folder_entry):
            widget.configure(state=state)
        self.extract_button.configure(
            state='disabled' if busy or self.info is None else 'normal')

    def _start(self, action, path, destination=None):
        if self.busy:
            return
        self._set_busy(True)
        self.generation += 1
        generation = self.generation
        self.progress.start(10)
        self.status_var.set('Validating archive…' if action == 'inspect' else 'Extracting archive…')

        def work():
            try:
                if action == 'inspect':
                    result = inspect_archive(path)
                else:
                    result = extract_archive(path, destination)
                self.events.put((generation, action, result, None))
            except Exception as error:
                self.events.put((generation, action, None, str(error)))

        threading.Thread(target=work, daemon=True).start()

    def inspect(self):
        if self.busy:
            return
        self.info = None
        self.extract_button.configure(state='disabled')
        for item in self.tree.get_children():
            self.tree.delete(item)
        path = self.archive_var.get().strip()
        if not path or not Path(path).is_file():
            self.status_var.set('Choose an existing CAT archive.')
            return
        self._start('inspect', path)

    def extract(self):
        if self.busy or self.info is None:
            return
        archive = self.archive_var.get().strip()
        folder = self.folder_var.get().strip()
        if not folder or folder in ('.', '..') or '/' in folder or '\\' in folder:
            messagebox.showerror('Invalid folder name', 'Choose a single, valid folder name.', parent=self.root)
            return
        destination = Path(self.parent_var.get().strip()) / folder
        if os.path.lexists(str(destination)):
            messagebox.showerror('Folder already exists', 'Choose a new folder name or location.', parent=self.root)
            return
        self._start('extract', archive, str(destination))

    def _poll(self):
        try:
            while True:
                generation, action, result, error = self.events.get_nowait()
                if generation != self.generation:
                    continue
                self._set_busy(False)
                self.progress.stop()
                if error:
                    self.status_var.set('Archive validation failed.' if action == 'inspect' else 'Extraction failed.')
                    messagebox.showerror('CATS Archive', error, parent=self.root)
                    continue
                if action == 'inspect':
                    self.info = result
                    for entry in result.entries:
                        self.tree.insert('', 'end', text=safe_display_path(entry.path),
                                         values=('Directory' if entry.kind == 1 else 'File',
                                                 '' if entry.kind == 1 else human_size(entry.size),
                                                 '%04o' % entry.mode))
                    self.status_var.set('Verified CAT v%d · %d entries · %s' %
                                         (result.version, len(result.entries), human_size(result.total_bytes)))
                    self.extract_button.configure(state='normal')
                else:
                    self.status_var.set('Extracted to %s' % result.path)
                    messagebox.showinfo('CATS Archive', 'Archive extracted successfully.', parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)


def main():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        sys.stderr.write('CATS GUI requires a graphical desktop: %s\n' % error)
        return 1
    arguments = [arg for arg in sys.argv[1:] if not arg.startswith('-psn_')]
    initial_archive = arguments[0] if arguments else None
    CatWindow(root, initial_archive)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
