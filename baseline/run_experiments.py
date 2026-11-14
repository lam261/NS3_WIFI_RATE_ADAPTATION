#!/usr/bin/env python3
"""Run from the ns-3 root after copying sources to scratch/. Python stdlib only."""
import argparse
import csv
import pathlib
import shlex
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ns3-root', type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument('--out', type=pathlib.Path, default=pathlib.Path('results-rr'))
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--distances', default='10,20,30,35,40,45,50')
    parser.add_argument('--algorithms', default='ARF,AARF,AMRR')
    parser.add_argument('--rts', default='0,1')
    parser.add_argument('--scenario', choices=['static', 'step'], default='static')
    parser.add_argument('--fixed-mode', default='OfdmRate18Mbps')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--max-success', type=int, default=50)
    parser.add_argument('--no-rts-high-load', action='store_true',
                        help='For RTS off only: 50000 packets, interval 0.46 ms, duration 23 s')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    distances = [float(x) for x in args.distances.split(',')]
    algorithms = args.algorithms.split(',')
    rts_values = [int(x) for x in args.rts.split(',')]
    if args.runs < 1 or not distances or min(distances) <= 0:
        parser.error('runs and distances must be positive')
    if not set(algorithms) <= {'ARF', 'AARF', 'AMRR', 'Fixed'} or not set(rts_values) <= {0, 1}:
        parser.error('unknown algorithm or RTS setting')
    root = args.ns3_root.resolve()
    out = args.out.resolve()
    ns3 = root / 'ns3'
    if not args.dry_run and not ns3.is_file():
        parser.error('ns3 wrapper not found; use --ns3-root')
    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)
        if (out / 'all-runs.csv').exists():
            parser.error('Output already contains results. Choose a new --out directory.')
        subprocess.run([sys.executable, str(ns3), 'build', 'rr-rate-adaptation'], cwd=root, check=True)
    rows = []
    # The step scenario has one near->far configuration, independent of distances.
    for distance in (distances if args.scenario == 'static' else [10.0]):
        for rts in rts_values:
            for run in range(1, args.runs + 1):
                for algorithm in algorithms:
                    name = f'{args.scenario}-{algorithm}-d{distance:g}-rts{rts}-run{run}'
                    prefix = out / name
                    options = dict(algorithm=algorithm, scenario=args.scenario, distance=distance,
                                   rts=rts, seed=args.seed, run=run, maxSuccess=args.max_success,
                                   fixedMode=args.fixed_mode, prefix=str(prefix))
                    if args.no_rts_high_load and not rts:
                        options.update(packets=50000, interval=0.00046, duration=23)
                    expression = 'scratch/rr-rate-adaptation ' + ' '.join(
                        f'--{key}={shlex.quote(str(value))}' for key, value in options.items())
                    command = [sys.executable, str(ns3), 'run', expression, '--no-build']
                    print(name, flush=True)
                    if args.dry_run:
                        print(shlex.join(command))
                        continue
                    if pathlib.Path(str(prefix) + '-summary.csv').exists():
                        raise RuntimeError(f'Refusing to overwrite {prefix}')
                    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
                    pathlib.Path(str(prefix) + '-console.log').write_text(
                        result.stdout + '\n' + result.stderr, encoding='utf-8')
                    result.check_returncode()
                    with open(str(prefix) + '-summary.csv', newline='') as stream:
                        row, = list(csv.DictReader(stream))
                    if int(row['tx_packets']) == 0:
                        raise RuntimeError('No UDP packet sent: inspect console log')
                    rows.append(row)
                    # Save completed runs even if a later process fails.
                    with (out / 'all-runs.csv').open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerows(rows)
    print(f'Completed {len(rows)} simulations' if not args.dry_run else 'Dry run only; no simulation executed')


if __name__ == '__main__':
    main()
