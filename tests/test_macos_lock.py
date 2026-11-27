"""macos/requirements.lock.txt stays in step with the locks the other builds test."""

import re
from pathlib import Path

from packaging.markers import Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parent.parent
MAC_LOCK = REPO / 'macos' / 'requirements.lock.txt'
BUILD_CONSTRAINTS = REPO / 'macos' / 'build-constraints.txt'
SHARED_LOCKS = [REPO / 'requirements.lock.txt', REPO / 'requirements.restricted.lock.txt']
# The app's interpreter and platform (macos/compile-lock.sh).
MAC_ENV = {'sys_platform': 'darwin', 'platform_system': 'Darwin', 'platform_machine': 'arm64',
           'python_version': '3.12', 'python_full_version': '3.12.16', 'os_name': 'posix',
           'implementation_name': 'cpython', 'platform_python_implementation': 'CPython'}
PIN = re.compile(r'^([A-Za-z0-9_.-]+)==(\S+)\s*(?:;\s*(.+?))?\s*(\\)?$')


def _pins(path):
    pins = {}
    for line in path.read_text().splitlines():
        match = PIN.match(line)
        if match and (match[3] is None or Marker(match[3]).evaluate(MAC_ENV)):
            pins[canonicalize_name(match[1])] = match[2]
    return pins


def test_every_shared_pin_keeps_its_version_on_the_mac():
    mac = _pins(MAC_LOCK)
    shared = {}
    for lock in SHARED_LOCKS:
        shared.update(_pins(lock))
    drift = {name: (mac[name], shared[name]) for name in mac.keys() & shared.keys() if mac[name] != shared[name]}
    assert not drift, f'regenerate with macos/compile-lock.sh: {drift}'


def test_every_requirement_is_in_the_mac_lock():
    # A dependency added to requirements.txt without running compile-lock.sh would be an
    # ImportError in the app only. compile-lock.sh leaves these out on purpose.
    left_out = {canonicalize_name(line.strip()) for line in (REPO / 'macos' / 'lock-excludes.txt').read_text().splitlines()
                if line.strip() and not line.strip().startswith('#')}
    mac = _pins(MAC_LOCK)
    missing = []
    for source in ('requirements.txt', 'requirements.restricted.txt'):
        for line in (REPO / source).read_text().splitlines():
            try:
                requirement = Requirement(line.split('#')[0].strip())
            except InvalidRequirement:
                continue
            name = canonicalize_name(requirement.name)
            if (requirement.marker is None or requirement.marker.evaluate(MAC_ENV)) and name not in left_out | mac.keys():
                missing.append(name)
    assert not missing, f'regenerate with macos/compile-lock.sh: {missing}'


def test_build_constraints_use_the_locked_versions():
    mac = _pins(MAC_LOCK)
    build = _pins(BUILD_CONSTRAINTS)
    assert build and {name: mac.get(name) for name in build} == build


def _blocks(path):
    return re.split(r'\n(?=[A-Za-z0-9_.-]+==)', path.read_text())


def test_every_pin_is_hashed():
    for path in (MAC_LOCK, BUILD_CONSTRAINTS):
        unhashed = [block.split()[0] for block in _blocks(path) if '==' in block.split()[0] and '--hash=sha256:' not in block]
        assert not unhashed, path.name


def test_only_the_headless_opencv_is_installed():
    mac = _pins(MAC_LOCK)
    assert 'opencv-python-headless' in mac
    assert 'opencv-python' not in mac


def test_torch_matches_the_windows_installer():
    setup = (REPO / 'installer' / 'Setup-Facet.ps1').read_text()
    current = re.search(r"else \{ @\('torch==([\d.]+)', 'torchvision==([\d.]+)'\) \}", setup)
    assert current, 'Setup-Facet.ps1 torch pin moved: update this test'
    mac = _pins(MAC_LOCK)
    assert (mac['torch'], mac['torchvision']) == current.groups()


def test_the_app_bundles_the_same_exiftool_as_the_docker_image():
    # 13.23-13.27 corrupt darktable XMP sidecars: one pin, checked in two places.
    docker = (REPO / 'Dockerfile').read_text()
    build = (REPO / 'macos' / 'build-app.sh').read_text()
    for name in ('EXIFTOOL_VERSION', 'EXIFTOOL_SHA256'):
        pinned = re.search(rf'^ARG {name}=(\S+)$', docker, re.M)
        bundled = re.search(rf'^{name}=(\S+)$', build, re.M)
        assert pinned and bundled and pinned[1] == bundled[1], name
