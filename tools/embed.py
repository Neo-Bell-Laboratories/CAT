import json
import pathlib
import sys
text = pathlib.Path(sys.argv[1]).read_text()
pathlib.Path(sys.argv[2]).write_text('static const char cat_table_source[] =\n' + '\n'.join(json.dumps(line) for line in text.splitlines(keepends=True)) + ';\n')
