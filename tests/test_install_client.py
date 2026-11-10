"""Exercise installer upgrades without installing packages or touching a real venv."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='install.sh uses bash')


@pytest.fixture
def installer(tmp_path):
    stubs = tmp_path / 'bin'
    stubs.mkdir()
    work = tmp_path / 'checkout'
    client = work / 'client'
    client.mkdir(parents=True)
    (client / 'package.json').write_text('{"scripts":{"build":"ng build"}}', encoding='utf-8')
    (client / 'package-lock.json').write_text('{}', encoding='utf-8')
    dist = client / 'dist' / 'client' / 'browser'
    dist.mkdir(parents=True)
    (dist / 'index.html').write_text('OLD', encoding='utf-8')
    log = tmp_path / 'commands.log'
    scripts = {
        'python3.12': '''#!/bin/bash
if [[ "$1" == --version ]]; then echo 'Python 3.12'; exit 0; fi
if [[ "$1" == -c && "$2" == *version_info* ]]; then exec "$REAL_PYTHON" -c "$2"; fi
exit 0
''',
        'pip': '''#!/bin/bash
printf 'pip %s\\n' "$*" >> "$LOG"
''',
        'node': '''#!/bin/bash
printf '%s\\n' "$FAKE_NODE"
''',
        'npm': '''#!/bin/bash
printf 'npm %s\\n' "$*" >> "$LOG"
if [[ "$1" == ci ]]; then exit "$CI_RC"; fi
if [[ "$1" == run && "$2" == build ]]; then
  output=dist/client
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == --output-path ]]; then output="$2"; break; fi
    shift
  done
  mkdir -p "$output/browser"
  printf NEW > "$output/browser/index.html"
  exit "$BUILD_RC"
fi
''',
        'npx': '''#!/bin/bash
printf 'npx %s\\n' "$*" >> "$LOG"
mkdir -p dist/client/browser
printf NEW > dist/client/browser/index.html
exit "$BUILD_RC"
''',
        'mv': '''#!/bin/bash
if [[ "$1" == -- ]]; then shift; fi
if [[ "$FAIL_PUBLISH" == 1 && "$1" == *'/.facet-build.'*'/client' && "$2" == *'/dist/client' ]]; then
  exit 9
fi
exec /bin/mv "$@"
''',
    }
    for name, script in scripts.items():
        path = stubs / name
        path.write_text(script, encoding='utf-8')
        path.chmod(0o755)

    def run(*flags, node='v24.15.0', ci_rc=0, build_rc=0, fail_publish=False):
        log.write_text('', encoding='utf-8')
        env = {**os.environ, 'PATH': f'{stubs}:/usr/bin:/bin', 'VIRTUAL_ENV': '/fake/venv',
               'REAL_PYTHON': sys.executable, 'LOG': str(log), 'FAKE_NODE': node,
               'CI_RC': str(ci_rc), 'BUILD_RC': str(build_rc), 'FAIL_PUBLISH': str(int(fail_publish))}
        result = subprocess.run(
            ['bash', str(ROOT / 'install.sh'), '--cpu', '--no-uv', *flags],
            cwd=work, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        return result, log.read_text(encoding='utf-8')

    return run, client, dist / 'index.html'


@pytest.mark.parametrize('node', ['v18.20.0', 'v20.19.0', 'v22.22.3', 'v24.14.9', 'v25.0.0', 'v26.0.0', 'unknown'])
def test_wrong_node_is_refused_before_dependency_installs(installer, node):
    run, client, old_index = installer
    result, log = run(node=node)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Node.js 24.15.0+' in result.stdout + result.stderr
    assert not log, 'node preflight must run before pip/npm can change the installation'
    assert old_index.read_text(encoding='utf-8') == 'OLD'
    assert not list(client.glob('.facet-build.*'))


@pytest.mark.parametrize('node', ['v24.15.0', 'v24.22.1'])
def test_upgrade_rebuilds_existing_frontend_with_the_lockfile(installer, node):
    run, client, old_index = installer
    result, log = run(node=node)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'npm ci --no-audit --no-fund' in log
    assert 'npm run build -- --output-path ' in log
    assert old_index.read_text(encoding='utf-8') == 'NEW'
    assert not list(client.glob('.facet-build.*'))


@pytest.mark.parametrize('failure', [{'ci_rc': 7}, {'build_rc': 8}, {'fail_publish': True}])
def test_failed_upgrade_preserves_previous_build(installer, failure):
    run, client, old_index = installer
    result, _ = run(**failure)
    assert result.returncode != 0
    assert old_index.read_text(encoding='utf-8') == 'OLD'
    assert not list(client.glob('.facet-build.*'))


def test_explicit_skip_client_needs_no_supported_node_and_keeps_build(installer):
    run, client, old_index = installer
    result, log = run('--skip-client', node='v18.0.0')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'npm ' not in log
    assert old_index.read_text(encoding='utf-8') == 'OLD'
    assert not list(client.glob('.facet-build.*'))


def test_an_empty_dist_is_not_a_completed_build(installer):
    run, _, old_index = installer
    old_index.unlink()
    result, log = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'npm ci' in log
    assert old_index.read_text(encoding='utf-8') == 'NEW'
