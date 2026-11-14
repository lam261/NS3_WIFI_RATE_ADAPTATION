#!/usr/bin/env python3
"""Install a separate scratch target without replacing the original experiment."""
import argparse
import pathlib
import subprocess
import sys
import tempfile

SOURCES = ('rr-extended.cc', 'rr-ext-core.h', 'rr-ext-manager.h')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ns3-root', type=pathlib.Path, required=True)
    a = p.parse_args()
    root = a.ns3_root.expanduser().resolve()
    pkg = pathlib.Path(__file__).resolve().parent
    if not (root / 'ns3').is_file() or not (root / 'scratch').is_dir():
        p.error('Use the ns-3.45 root containing ns3 and scratch/')
    version = (root / 'VERSION').read_text().strip() if (root / 'VERSION').exists() else ''
    if not version.startswith('3.45'):
        p.error(f'Expected ns-3.45, VERSION={version!r}')
    for name in SOURCES:
        dest = root / 'scratch' / name
        if dest.exists() and dest.read_bytes() != (pkg / name).read_bytes():
            p.error(f'Existing extension differs: {dest}. Use a separate checkout or move that extension aside.')
    # Tests run BEFORE copying/building. The file has a separate main().
    with tempfile.TemporaryDirectory(prefix='rr-ext-core-') as tmp:
        exe = pathlib.Path(tmp) / 'core-tests'
        subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-pedantic',
                        str(pkg / 'core-tests.cc'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    for name in SOURCES:
        dest = root / 'scratch' / name
        if not dest.exists():
            dest.write_bytes((pkg / name).read_bytes())
    subprocess.run([sys.executable, str(root / 'ns3'), 'build', 'rr-extended'],
                   cwd=root, check=True)
    print('PASS: installed scratch/rr-extended; original scratch/rr-rate-adaptation untouched')


if __name__ == '__main__':
    main()
