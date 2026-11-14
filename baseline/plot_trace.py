#!/usr/bin/env python3
"""Plot one or several real simulation traces, including step scenarios."""
import argparse
import csv
import pathlib


def read(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefixes', nargs='+', type=pathlib.Path)
    parser.add_argument('--out', type=pathlib.Path, default=pathlib.Path('trace.png'))
    args = parser.parse_args()
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True, layout='constrained')
    for prefix in args.prefixes:
        summary, = read(pathlib.Path(str(prefix)+'-summary.csv'))
        label = summary['algorithm']
        series = read(pathlib.Path(str(prefix)+'-timeseries.csv'))
        rates = read(pathlib.Path(str(prefix)+'-rates.csv'))
        state = read(pathlib.Path(str(prefix)+'-state.csv'))
        end = float(summary['duration_s'])
        axes[0].plot([float(r['time_s'])-2 for r in series],
                     [float(r['goodput_mbps']) for r in series], marker='.', label=label)
        if rates:
            times = [float(r['time_s'])-2 for r in rates]
            values = [float(r['selected_data_rate_mbps']) for r in rates]
            if times[-1] < end:
                times.append(end); values.append(values[-1])
            axes[1].step(times, values, where='post', label=label)
        elif label=='Fixed':
            mode = summary['fixed_mode'].removeprefix('OfdmRate').removesuffix('Mbps')
            axes[1].hlines(float(mode),0,float(summary['duration_s']),label=label)
        if state:
            times = [float(r['time_s'])-2 for r in state]
            values = [float(r['success_threshold']) for r in state]
            if times[-1] < end:
                times.append(end); values.append(values[-1])
            axes[2].step(times, values, where='post', label=label)
        if summary['scenario']=='step':
            for ax in axes:
                ax.axvline(float(summary['switch_s']), color='gray', linestyle='--', alpha=.5)
    axes[0].set_ylabel('UDP goodput (Mb/s)')
    axes[1].set_ylabel('Selected DATA rate (Mb/s)')
    axes[2].set_ylabel('Success threshold')
    axes[2].set_xlabel('Time since traffic start (s)')
    axes[0].set_title('Rate adaptation traces (one run per curve)')
    for ax in axes:
        ax.grid(alpha=.25)
        if ax.get_legend_handles_labels()[0]:
            ax.legend()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=180)
    plt.close(fig)
    print(args.out)


if __name__=='__main__':
    main()
