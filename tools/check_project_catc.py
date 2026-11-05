"""Cross-check the installed CATS CLI against this build from every peer project."""
import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cats', '--catc', dest='cats',
                    default=os.environ.get('CATS', os.environ.get('CATC', 'cats')),
                    help='installed/shared CLI (default: CATS, legacy CATC, or cats on PATH)')
parser.add_argument('--reference-cats', '--reference-catc', dest='reference_cats',
                    default=os.environ.get('CATS_REFERENCE', os.environ.get('CATC_REFERENCE',
                                            str(Path(__file__).resolve().parents[1] / 'bin/cats'))),
                    help='current-source CAT binary used for interoperability checks')
parser.add_argument('--projects-root', type=Path,
                    default=Path(__file__).resolve().parents[2])
args = parser.parse_args()

projects = ('CAAT', 'CEP', 'CIT', 'CITP', 'CVCS', 'css', 'ssqlite')

def resolve(name, description):
    binary = shutil.which(name)
    if binary is None:
        sys.exit(description + ' not found or not executable: ' + name)
    return str(Path(binary).resolve())

def get_version(binary):
    try:
        return subprocess.check_output([binary, '--version'], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(binary + ' could not report its version: ' + str(error))

def format_versions(version):
    default = re.search(r'\bformat=([0-9]+(?:\.[0-9]+)?)\b', version)
    compact = re.search(r'\bcompact_format=([0-9]+(?:\.[0-9]+)?)\b', version)
    return (default.group(1) if default else None,
            compact.group(1) if compact else None)

binary = resolve(args.cats, 'Shared CATS CLI')
reference = resolve(args.reference_cats, 'Current-source CATS CLI')
version = get_version(binary)
reference_version = get_version(reference)
shared_formats = format_versions(version)
reference_formats = format_versions(reference_version)
if not all(shared_formats) or not all(reference_formats):
    sys.exit('CATS CLI version output must declare format=N.N and compact_format=N.N')
if shared_formats != reference_formats:
    sys.exit('CATS CLI format mismatch: installed=%s current=%s' %
             (shared_formats, reference_formats))

projects_root = args.projects_root.resolve()
missing = [name for name in projects if not (projects_root / name).is_dir()]
if missing:
    sys.exit('project directories not found: ' + ', '.join(missing))

payload = (b'CAT shared CLI interoperability test\x00\xff\r\n' * 1024)

def run(command, project):
    try:
        result = subprocess.run(command, cwd=project, check=False,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
    except OSError as error:
        sys.exit('%s cannot run %s: %s' % (project.name, command[0], error))
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        sys.exit('%s: %s failed (%d): %s' %
                 (project.name, command[1], result.returncode, detail))
    return result

def assert_restore(destination, source, project):
    restored = destination / source.name
    if not restored.is_file() or restored.read_bytes() != payload:
        sys.exit('%s: cross-version CAT round trip changed file bytes' % project.name)
    if stat.S_IMODE(restored.stat().st_mode) != 0o640:
        sys.exit('%s: cross-version CAT round trip changed file mode' % project.name)

for name in projects:
    project = projects_root / name
    with tempfile.TemporaryDirectory(prefix='cats-peer-smoke-') as temporary:
        root = Path(temporary)
        source = root / 'source file with spaces.bin'
        source.write_bytes(payload)
        source.chmod(0o640)

        for compact in (False, True):
            mode = 'compact' if compact else 'default'
            option = ['-c'] if compact else []
            decode_option = ['-c'] if compact else []

            shared_archive = root / ('shared-' + mode + '.cat')
            shared_output = root / ('shared-' + mode + ' restored')
            run([binary, '-e', *option, str(source), '--output', str(shared_archive)], project)
            run([reference, '-v', str(shared_archive)], project)
            run([reference, '-d', *decode_option, str(shared_archive), str(shared_output)], project)
            assert_restore(shared_output, source, project)

            current_archive = root / ('current-' + mode + '.cat')
            current_output = root / ('current-' + mode + ' restored')
            run([reference, '-e', *option, str(source), '--output', str(current_archive)], project)
            run([binary, '-v', str(current_archive)], project)
            run([binary, '-d', *decode_option, str(current_archive), str(current_output)], project)
            assert_restore(current_output, source, project)
    print('%s: bidirectional default %s / compact %s compatibility passed (%s <-> current source)' %
          (name, shared_formats[0], shared_formats[1], version))

print('PASS: shared cats interoperates bidirectionally in both framing modes with the current build in all seven peer directories')
