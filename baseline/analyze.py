#!/usr/bin/env python3
"""Aggregate independent runs; scipy/matplotlib required. Never invent missing data."""
import argparse
import csv
import math
import pathlib
import statistics
from collections import defaultdict


def estimate(values, t_distribution):
    values = [x for x in values if math.isfinite(x)]
    if not values:
        return 0, float('nan'), float('nan')
    average = statistics.mean(values)
    ci = (float(t_distribution.ppf(0.975, len(values)-1)) * statistics.stdev(values)
          / math.sqrt(len(values))) if len(values) > 1 else float('nan')
    return len(values), average, ci


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from scipy.stats import t
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=pathlib.Path)
    parser.add_argument('--out', type=pathlib.Path, default=pathlib.Path('analysis-rr'))
    args = parser.parse_args()
    with args.input.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        parser.error('No results')
    metrics = ['goodput_mbps', 'pdr', 'mean_delay_ms',
               'data_failed_callbacks', 'final_data_failed_callbacks']
    ignored = set(metrics + ['seed', 'run', 'tx_packets', 'rx_packets'])
    keys = [k for k in rows[0] if k not in ignored]
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        key = tuple(row[k] for k in keys)
        identity = key + (row['seed'], row['run'])
        if identity in seen:
            raise ValueError('Duplicate seed/run within condition')
        seen.add(identity)
        groups[key].append(row)
    args.out.mkdir(parents=True, exist_ok=True)
    output = []
    for key, group in groups.items():
        record = dict(zip(keys, key))
        for metric in metrics:
            n, average, ci = estimate([float(row[metric]) for row in group], t)
            record.update({f'{metric}_n': n, f'{metric}_mean': average, f'{metric}_ci95': ci})
        output.append(record)
    with (args.out / 'aggregate.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=output[0].keys())
        writer.writeheader(); writer.writerows(output)
    # Separate panels for different physical/load/parameter configurations.
    facet_keys = [k for k in keys if k not in ['algorithm', 'distance_m', 'fixed_mode']]
    facets = defaultdict(list)
    for record in output:
        if record['scenario'] == 'static':
            facets[tuple(record[k] for k in facet_keys)].append(record)
    for index, (facet, records) in enumerate(facets.items()):
        fig, ax = plt.subplots(figsize=(7, 4.4), layout='constrained')
        for algorithm in sorted({r['algorithm'] for r in records}):
            for mode in sorted({r['fixed_mode'] for r in records if r['algorithm']==algorithm}):
                group = sorted((r for r in records if r['algorithm']==algorithm and r['fixed_mode']==mode),
                               key=lambda r: float(r['distance_m']))
                label = algorithm if algorithm != 'Fixed' else f'Fixed ({mode})'
                ax.errorbar([float(r['distance_m']) for r in group],
                            [r['goodput_mbps_mean'] for r in group],
                            yerr=[r['goodput_mbps_ci95'] if math.isfinite(r['goodput_mbps_ci95']) else 0
                                  for r in group], marker='o', capsize=3, label=label)
        metadata = dict(zip(facet_keys, facet))
        ax.set(xlabel='Distance (m)', ylabel='UDP goodput (Mb/s)',
               title=f"ns-3 RR-5208 adaptation; RTS={metadata['rts']}; 95% Student-t CI")
        ax.grid(alpha=.25); ax.legend()
        fig.savefig(args.out / f'goodput-{index}.png', dpi=180)
        plt.close(fig)
    # Paired AARF-ARF differences use matching scenario and RNG run.
    pair_keys = [k for k in keys if k != 'algorithm']
    matched = defaultdict(dict)
    for row in rows:
        if row['algorithm'] in ['ARF', 'AARF']:
            key = tuple(row[k] for k in pair_keys) + (row['seed'], row['run'])
            matched[key][row['algorithm']] = float(row['goodput_mbps'])
    deltas = defaultdict(list)
    for key, pair in matched.items():
        if len(pair)==2:
            deltas[key[:-2]].append(pair['AARF']-pair['ARF'])
    with (args.out/'paired-aarf-minus-arf.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(pair_keys+['n_pairs', 'delta_mbps_mean', 'delta_mbps_ci95'])
        for key, values in deltas.items():
            writer.writerow(list(key)+list(estimate(values,t)))
    print(f'Wrote {len(output)} condition summaries to {args.out}')


if __name__ == '__main__':
    main()
