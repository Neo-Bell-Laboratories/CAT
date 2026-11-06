"""Conservative release gate: missing evidence is a failure, never a pass."""
import json
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parent.parent
blockers=[]
for path in [root/'LICENSE',root/'licenses/XF-MIT.txt',root/'licenses/LambdaScript-MIT.txt',
             root/'licenses/zlib-system.LICENSE.txt',root/'licenses/stb_image.h.LICENSE.txt',
             root/'licenses/stb_image_write.h.LICENSE.txt']:
    if not path.is_file():blockers.append('missing bundled license/ownership record: '+str(path))
report=root/'docs/release-validation.json'
if not report.exists():blockers.append('release validation report is missing')
else:
    data=json.loads(report.read_text())
    for gate in ['macos_release','macos_asan_ubsan','macos_lsan','macos_tsan','macos_gui_bundle','packaging',
                 'linux_release','linux_lsan','linux_asan_ubsan','linux_tsan','cross_platform_exchange',
                 'streaming','failure_injection','archive_fuzz','tree_fuzz','linux_gui','windows_gui','application_target_builds','shared_cli_integration','ci']:
        if data.get(gate,{}).get('status')!='passed':blockers.append('validation not passed: '+gate)
if blockers:
    print('NOT READY FOR PUBLIC PRODUCTION RELEASE')
    print('\n'.join('- '+item for item in blockers))
    sys.exit(1)
print('Recorded gates passed. A maintainer must review provenance, results and release artifacts before publishing.')
