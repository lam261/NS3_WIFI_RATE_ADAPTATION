#!/usr/bin/env python3
"""Reproducible extended ns-3.45 experiments. Python standard library only."""
import argparse
import csv
import hashlib
import json
import math
import pathlib
import shlex
import subprocess
import sys

VERSION = 1
ALGORITHMS = ('ARF', 'AARF', 'AMRR')
RATES = (6, 9, 12, 18, 24, 36, 48, 54)
BASE = dict(minSuccess=10, maxSuccess=50, minTimeout=15, successK=2, timeoutK=1.5)
SWEEPS = dict(maxSuccess=(20, 50, 80, 100), successK=(1.5, 2, 3),
              timeoutK=(1, 1.5, 2), minSuccess=(5, 10, 20), minTimeout=(10, 15, 30))
SOURCES = ('rr-extended.cc', 'rr-ext-core.h', 'rr-ext-manager.h')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def variants():
    result = [('baseline', dict(BASE))]
    for key, values in SWEEPS.items():
        for value in values:
            if value != BASE[key]:
                result.append((f'{key}={value:g}', dict(BASE, **{key: value})))
    return result


def make_cases(suite, runs=10, first_run=11, seed=1):
    cases = []

    def add(family, label, **opts):
        options = dict(algorithm='AARF', scenario='static', distance=20,
                       nearDistance=20, farDistance=40, switchTime=12,
                       packets=30000, interval=0.0008, duration=24,
                       packetSize=2268, drain=1, sample=1, rts=0, paperRates=1,
                       fixedMode='OfdmRate18Mbps', seed=seed, run=first_run,
                       txPower=16, noiseFigure=7, exponent=3, referenceLoss=46.6777,
                       amrrPeriod=1, traceState=0, pcap=0, **BASE)
        options.update(opts)
        identity = digest(dict(family=family, label=label, options=options))[:16]
        cases.append(dict(case_id=f'{family}-{identity}', suite=family,
                          config_label=label, options=options))

    suites = ('step', 'rts', 'fixed', 'sensitivity') if suite == 'all' else (suite,)
    for family in suites:
        if family == 'smoke':
            for rts in (0, 1):
                add(family, f'AARF-rts{rts}', rts=rts, packets=5000, duration=4,
                    sample=0.25, traceState=1, pcap=1)
            for rate in (9, 48):
                add(family, f'Fixed-{rate}', algorithm='Fixed',
                    fixedMode=f'OfdmRate{rate}Mbps', packets=5000, duration=4, sample=0.25)
            for start, end in ((20, 40), (40, 20)):
                add(family, f'step-{start}-to-{end}', scenario='step', distance=start,
                    nearDistance=start, farDistance=end, switchTime=2,
                    packets=5000, duration=4, sample=0.25, traceState=1)
            continue
        for run in range(first_run, first_run + runs):
            if family == 'step':
                for start, end in ((20, 40), (40, 20)):
                    for alg in ALGORITHMS:
                        add(family, f'{start}-to-{end}', algorithm=alg, scenario='step',
                            distance=start, nearDistance=start, farDistance=end, run=run,
                            sample=0.25, traceState=int(run == first_run))
            elif family == 'rts':
                for d in (20, 35, 40, 45, 50):
                    for alg in ALGORITHMS:
                        for rts in (0, 1):
                            add(family, 'same-load', algorithm=alg, distance=d, rts=rts, run=run)
            elif family == 'fixed':
                for d in (20, 35, 40, 45, 50):
                    for rate in RATES:
                        add(family, f'fixed-{rate}', algorithm='Fixed', distance=d, run=run,
                            fixedMode=f'OfdmRate{rate}Mbps')
                    # Fresh adaptive controls with exactly the same load, distance and RNG labels.
                    for alg in ALGORITHMS:
                        add(family, 'adaptive-control', algorithm=alg, distance=d, run=run)
            elif family == 'sensitivity':
                for label, parameters in variants():
                    for d in (35, 40):
                        add(family, label, distance=d, run=run, **parameters)
            else:
                raise ValueError(family)
    return cases


def read_one(path):
    with path.open(newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1:
        raise ValueError(f'Expected one summary row: {path}')
    return rows[0]


def check_case(directory, case):
    prefix = directory / case['case_id']
    row = read_one(pathlib.Path(str(prefix) + '-summary.csv'))
    names = dict(algorithm='algorithm', scenario='scenario', distance='distance_m',
                 nearDistance='near_m', farDistance='far_m', switchTime='switch_s',
                 rts='rts', paperRates='paper_rates', seed='seed', run='run',
                 duration='duration_s', packetSize='packet_size', packets='planned_packets',
                 interval='interval_s', txPower='tx_power_dbm', noiseFigure='noise_figure_db',
                 exponent='exponent', referenceLoss='reference_loss_db', minSuccess='min_success',
                 maxSuccess='max_success', minTimeout='min_timeout', successK='success_k',
                 timeoutK='timeout_k', amrrPeriod='amrr_period_s', fixedMode='fixed_mode')
    for option, column in names.items():
        expected = case['options'][option]
        if isinstance(expected, str):
            equal = row[column] == expected
        else:
            equal = math.isclose(float(row[column]), expected, rel_tol=1e-10, abs_tol=1e-10)
        if not equal:
            raise ValueError(f'{prefix}: {column}={row[column]} expected {expected}')
    tx, rx = int(row['tx_packets']), int(row['rx_packets'])
    if tx != case['options']['packets'] or not 0 <= rx <= tx:
        raise ValueError(f'{prefix}: invalid UDP counts {rx}/{tx}')
    goodput = rx * int(row['packet_size']) * 8 / float(row['duration_s']) / 1e6
    if not math.isclose(float(row['goodput_mbps']), goodput, abs_tol=1e-8):
        raise ValueError(f'{prefix}: inconsistent goodput')
    if not math.isclose(float(row['pdr']), rx / tx, abs_tol=1e-10):
        raise ValueError(f'{prefix}: inconsistent PDR')
    delay = float(row['mean_delay_ms'])
    if (rx and (not math.isfinite(delay) or delay < 0)) or (not rx and not math.isnan(delay)):
        raise ValueError(f'{prefix}: invalid mean delay')
    with pathlib.Path(str(prefix) + '-timeseries.csv').open(newline='') as f:
        series = list(csv.DictReader(f))
    previous, bits = 2.0, 0.0
    for bin_row in series:
        now = float(bin_row['time_s'])
        if now <= previous or now > 2 + case['options']['duration'] + 1e-8:
            raise ValueError(f'{prefix}: invalid timeseries timestamps')
        expected_end = min(previous + case['options']['sample'], 2 + case['options']['duration'])
        if not math.isclose(now, expected_end, abs_tol=1e-8):
            raise ValueError(f'{prefix}: missing/nonuniform bin')
        value = float(bin_row['goodput_mbps'])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f'{prefix}: invalid timeseries goodput')
        bits += value * (now - previous) * 1e6
        previous = now
    if not math.isclose(previous, 2 + case['options']['duration'], abs_tol=1e-8):
        raise ValueError(f'{prefix}: incomplete timeseries')
    if not math.isclose(bits, rx * int(row['packet_size']) * 8, abs_tol=0.1):
        raise ValueError(f'{prefix}: summary/timeseries disagree')
    state_path = pathlib.Path(str(prefix) + '-state.csv')
    if not state_path.is_file() or not pathlib.Path(str(prefix) + '-rates.csv').is_file():
        raise ValueError(f'{prefix}: missing trace files')
    if case['options']['traceState'] and len(state_path.read_text().splitlines()) < 2:
        raise ValueError(f'{prefix}: empty state trace')
    if case['suite'] == 'smoke' and rx == 0:
        raise ValueError(f'{prefix}: smoke received zero packets')
    return dict(case_id=case['case_id'], suite=case['suite'],
                config_label=case['config_label'], sample_s=case['options']['sample'], **row)


def atomic_json(path, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def write_rows(out, rows):
    if not rows:
        return
    tmp = out / 'all-runs.csv.tmp'
    with tmp.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    tmp.replace(out / 'all-runs.csv')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ns3-root', type=pathlib.Path, default=pathlib.Path.cwd())
    p.add_argument('--out', type=pathlib.Path, required=True)
    p.add_argument('--suite', choices=['smoke', 'step', 'rts', 'fixed', 'sensitivity', 'all'], required=True)
    p.add_argument('--runs', type=int, default=10)
    p.add_argument('--first-run', type=int, default=11)
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    if not 1 <= a.first_run <= a.first_run + a.runs - 1 <= 2**32 - 1 or not 1 <= a.seed <= 2**32 - 1:
        p.error('runs/first-run/seed must be positive, run must fit uint32')
    root, out = a.ns3_root.expanduser().resolve(), a.out.expanduser().resolve()
    pkg = pathlib.Path(__file__).resolve().parent
    hashes = {n: hashlib.sha256((pkg / n).read_bytes()).hexdigest() for n in SOURCES}
    cases = make_cases(a.suite, a.runs, a.first_run, a.seed)
    plan = dict(version=VERSION, ns3_version='3.45', source_hashes=hashes, cases=cases)
    if a.dry_run:
        counts = {s: sum(c['suite'] == s for c in cases) for s in sorted({c['suite'] for c in cases})}
        print(json.dumps(dict(total=len(cases), by_suite=counts, first=cases[0], last=cases[-1]), indent=2))
        return
    if not (root / 'ns3').is_file():
        p.error('ns3 wrapper missing; run in Ubuntu/WSL and set --ns3-root')
    version = (root / 'VERSION').read_text().strip()
    if not version.startswith('3.45'):
        p.error(f'Expected ns-3.45; found {version}')
    for n in SOURCES:
        installed = root / 'scratch' / n
        if not installed.exists() or hashlib.sha256(installed.read_bytes()).hexdigest() != hashes[n]:
            p.error(f'Installed source mismatch: {installed}; run install.py')
    if out.exists() and any(out.iterdir()):
        if not a.resume or not (out / 'plan.json').is_file():
            p.error('Output is not empty. Use a new directory, or --resume with the SAME plan.')
        if json.loads((out / 'plan.json').read_text()) != plan:
            p.error('Resume plan/source mismatch. Keep all arguments unchanged or use a new output directory.')
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / 'plan.json', plan)
    subprocess.run([sys.executable, str(root / 'ns3'), 'build', 'rr-extended'], cwd=root, check=True)
    rows = []
    for number, case in enumerate(cases, 1):
        prefix = out / case['case_id']
        marker = pathlib.Path(str(prefix) + '-done.json')
        if a.resume and marker.exists():
            if json.loads(marker.read_text()) != case:
                raise ValueError(f'Bad completion marker {marker}')
            row = check_case(out, case)
            print(f'[{number}/{len(cases)}] verified, skip {case["case_id"]}', flush=True)
        else:
            options = dict(case['options'], prefix=str(prefix))
            expression = 'scratch/rr-extended ' + ' '.join(
                f'--{k}={shlex.quote(str(v))}' for k, v in options.items())
            print(f'[{number}/{len(cases)}] {case["suite"]} {case["config_label"]} '
                  f'{options["algorithm"]} d={options["distance"]} run={options["run"]}', flush=True)
            command = [sys.executable, str(root / 'ns3'), 'run', expression, '--no-build']
            atomic_json(pathlib.Path(str(prefix) + '-command.json'), command)
            with pathlib.Path(str(prefix) + '-console.log').open('w') as log:
                subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
            row = check_case(out, case)
            atomic_json(marker, case)
        rows.append(row)
        write_rows(out, rows)
    print(f'COMPLETE: {len(rows)} verified simulations -> {out / "all-runs.csv"}')


if __name__ == '__main__':
    main()
