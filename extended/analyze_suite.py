#!/usr/bin/env python3
"""Analyze completed extended experiments; CSV + print-quality PNG/SVG figures."""
import argparse
import csv
import json
import math
import pathlib
import statistics
from collections import defaultdict
from run_suite import BASE, SWEEPS, check_case

METRICS = ('goodput_mbps', 'pdr', 'mean_delay_ms')
COLORS = {'ARF': '#2166ac', 'AARF': '#c45d0b', 'AMRR': '#18805b'}
LABELS = {'goodput_mbps': 'UDP goodput (Mb/s)', 'pdr': 'PDR (%)',
          'mean_delay_ms': 'Mean one-way delay (ms)'}
PARAMS = dict(minSuccess='min_success', maxSuccess='max_success', minTimeout='min_timeout',
              successK='success_k', timeoutK='timeout_k')


def estimate(values):
    from scipy.stats import t
    values = [float(v) for v in values if math.isfinite(float(v))]
    if not values:
        return 0, math.nan, math.nan
    n = len(values)
    return n, statistics.mean(values), (float(t.ppf(.975, n - 1)) * statistics.stdev(values)
                                      / math.sqrt(n) if n > 1 else math.nan)


def write_csv(path, rows, columns=None):
    if not rows and columns is None:
        return
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns or list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def aggregate(rows, keys, metrics=METRICS):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    output = []
    for key, group in sorted(groups.items()):
        record = dict(zip(keys, key))
        for metric in metrics:
            n, mean, ci = estimate([r[metric] for r in group])
            record.update({metric + '_n': n, metric + '_mean': mean, metric + '_ci95': ci})
        output.append(record)
    return output


def paired(rows, match_keys, arm_column, treatment, control, metrics=METRICS):
    groups = defaultdict(dict)
    for row in rows:
        if row[arm_column] in (treatment, control):
            key = tuple(row[k] for k in match_keys) + (row['seed'], row['run'])
            arm = row[arm_column]
            if arm in groups[key]:
                raise ValueError('Duplicate paired observation')
            groups[key][arm] = row
    differences = []
    for key, arms in groups.items():
        if treatment in arms and control in arms:
            record = dict(zip(match_keys, key[:-2]))
            for m in metrics:
                record[m] = float(arms[treatment][m]) - float(arms[control][m])
            differences.append(record)
    out = aggregate(differences, match_keys, metrics)
    for row in out:
        row['difference'] = f'{treatment} minus {control}'
    return out


def phase_mean(series, start, end):
    """Integrate complete aligned bins, with times relative to UDP start."""
    weighted = 0.0
    covered = 0.0
    previous = 0.0
    for row in series:
        now, value = float(row['time_s']) - 2, float(row['goodput_mbps'])
        overlap = max(0, min(now, end) - max(previous, start))
        if overlap:
            if previous < start - 1e-8 or now > end + 1e-8:
                raise ValueError('Phase boundaries must align with timeseries bins')
            covered += overlap; weighted += overlap * value
        previous = now
    if not math.isclose(covered, end - start, abs_tol=1e-8):
        raise ValueError('Incomplete phase data')
    return weighted / covered


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=pathlib.Path, help='Completed suite directory containing plan.json')
    p.add_argument('--out', type=pathlib.Path, required=True)
    a = p.parse_args()
    src, out = a.input.expanduser().resolve(), a.out.expanduser().resolve()
    plan = json.loads((src / 'plan.json').read_text())
    rows = []
    for case in plan['cases']:
        marker = src / (case['case_id'] + '-done.json')
        if not marker.exists() or json.loads(marker.read_text()) != case:
            raise ValueError(f'Suite incomplete: {case["case_id"]}. Resume the batch first.')
        rows.append(check_case(src, case))
    out.mkdir(parents=True, exist_ok=True)
    # Rebuild from validated per-run files, rather than trusting an old merged CSV.
    write_csv(out / 'all-runs-verified.csv', rows)
    keys = ['suite', 'config_label', 'algorithm', 'scenario', 'distance_m', 'near_m', 'far_m',
            'switch_s', 'rts', 'fixed_mode', *PARAMS.values()]
    summaries = aggregate(rows, keys)
    write_csv(out / 'aggregate.csv', summaries)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False})

    def save(fig, name):
        fig.savefig(out / (name + '.png'), dpi=240)
        fig.savefig(out / (name + '.svg'))
        plt.close(fig)

    def plot_line(ax, group, x_key, label, metric, color=None):
        group = sorted(group, key=lambda r: float(r[x_key]))
        scale = 100 if metric == 'pdr' else 1
        # A single run has no CI; do not depict it as an estimated zero-width CI.
        cis = [r[metric + '_ci95'] for r in group]
        errors = [x * scale for x in cis] if all(math.isfinite(x) for x in cis) else None
        ax.errorbar([float(r[x_key]) for r in group],
                    [r[metric + '_mean'] * scale for r in group], yerr=errors,
                    marker='o', capsize=3, label=label, color=color)
        ax.grid(alpha=.22)

    rts = [r for r in summaries if r['suite'] == 'rts']
    if rts:
        paired_rts = paired([r for r in rows if r['suite'] == 'rts'],
                            ['algorithm', 'distance_m'], 'rts', '1', '0')
        # check_case returns native string summary values; keys above use strings.
        write_csv(out / 'rts-on-minus-off.csv', paired_rts)
        for metric in METRICS:
            fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True, layout='constrained')
            for ax, value in zip(axes, ('0', '1')):
                for alg in COLORS:
                    plot_line(ax, [r for r in rts if r['rts'] == value and r['algorithm'] == alg],
                              'distance_m', alg, metric, COLORS[alg])
                ax.set(title=f'RTS/CTS {"ON" if value == "1" else "OFF"}', xlabel='Distance (m)')
                ax.legend()
            axes[0].set_ylabel(LABELS[metric]); save(fig, 'rts-' + metric)

    fixed = [r for r in summaries if r['suite'] == 'fixed']
    if fixed:
        best = []
        for d in sorted({r['distance_m'] for r in fixed}, key=float):
            candidates = [r for r in fixed if r['distance_m'] == d and r['algorithm'] == 'Fixed']
            winner = max(candidates, key=lambda r: r['goodput_mbps_mean'])
            best.append(dict(distance_m=d, selected_fixed_mode=winner['fixed_mode'],
                             max_fixed_mean_mbps=winner['goodput_mbps_mean']))
        write_csv(out / 'best-fixed-mode.csv', best)
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True, layout='constrained')
        for mode in sorted({r['fixed_mode'] for r in fixed if r['algorithm'] == 'Fixed'},
                           key=lambda m: int(m.removeprefix('OfdmRate').removesuffix('Mbps'))):
            plot_line(axes[0], [r for r in fixed if r['algorithm'] == 'Fixed' and r['fixed_mode'] == mode],
                      'distance_m', mode.removeprefix('OfdmRate'), 'goodput_mbps')
        for alg in COLORS:
            plot_line(axes[1], [r for r in fixed if r['algorithm'] == alg], 'distance_m', alg,
                      'goodput_mbps', COLORS[alg])
        axes[1].plot([float(r['distance_m']) for r in best],
                     [r['max_fixed_mean_mbps'] for r in best], 'k--', label='Maximum fixed mean')
        for ax in axes:
            ax.set(xlabel='Distance (m)', ylabel=LABELS['goodput_mbps']); ax.legend(fontsize=8)
        axes[0].set_title('All eight fixed OFDM modes'); axes[1].set_title('Adaptive controls at the same load')
        save(fig, 'fixed-rates-and-adaptive')

    sensitivity = [r for r in summaries if r['suite'] == 'sensitivity']
    if sensitivity:
        deltas = []
        raw = [r for r in rows if r['suite'] == 'sensitivity']
        for label in sorted({r['config_label'] for r in raw} - {'baseline'}):
            deltas.extend(paired(raw, ['distance_m'], 'config_label', label, 'baseline'))
        write_csv(out / 'sensitivity-minus-baseline.csv', deltas)
        for metric in METRICS:
            fig, axes = plt.subplots(2, 3, figsize=(13, 7), layout='constrained')
            for ax, (option, values) in zip(axes.flat, SWEEPS.items()):
                column = PARAMS[option]
                for d in sorted({r['distance_m'] for r in sensitivity}, key=float):
                    selected = [r for r in sensitivity if r['distance_m'] == d and
                                (r['config_label'] == 'baseline' or r['config_label'].startswith(option + '='))]
                    plot_line(ax, selected, column, f'd={d} m', metric)
                ax.set(xlabel=option, ylabel=LABELS[metric], xticks=list(values)); ax.legend(fontsize=8)
                ax.axvline(BASE[option], linestyle=':', color='gray')
            axes.flat[-1].axis('off'); save(fig, 'sensitivity-' + metric)

    step = [r for r in rows if r['suite'] == 'step']
    if step:
        bins, phases = [], []
        for row in step:
            with (src / (row['case_id'] + '-timeseries.csv')).open(newline='') as f:
                series = list(csv.DictReader(f))
            for b in series:
                bins.append(dict(direction=row['config_label'], algorithm=row['algorithm'],
                                 time_s=float(b['time_s']) - 2, goodput_mbps=float(b['goodput_mbps'])))
            switch, duration = float(row['switch_s']), float(row['duration_s'])
            for label, start, end in [('before-switch', 0, switch),
                                      ('first-2s-after-switch', switch, switch + 2),
                                      ('last-4s', duration - 4, duration)]:
                phases.append(dict(direction=row['config_label'], algorithm=row['algorithm'],
                                   seed=row['seed'], run=row['run'], phase=label,
                                   window_start_s=start, window_end_s=end,
                                   goodput_mbps=phase_mean(series, start, end)))
        write_csv(out / 'step-phases-per-run.csv', phases)
        write_csv(out / 'step-phases-aggregate.csv', aggregate(phases,
                  ['direction', 'algorithm', 'phase', 'window_start_s', 'window_end_s'], ['goodput_mbps']))
        means = aggregate(bins, ['direction', 'algorithm', 'time_s'], ['goodput_mbps'])
        write_csv(out / 'step-bins-aggregate.csv', means)
        for direction in sorted({r['config_label'] for r in step}):
            fig, ax = plt.subplots(figsize=(8.5, 4.4), layout='constrained')
            for alg in COLORS:
                group = sorted([r for r in means if r['direction'] == direction and r['algorithm'] == alg],
                               key=lambda r: r['time_s'])
                x = np.array([r['time_s'] for r in group]); y = np.array([r['goodput_mbps_mean'] for r in group])
                ci = np.array([r['goodput_mbps_ci95'] for r in group])
                ax.plot(x, y, label=alg, color=COLORS[alg])
                if np.all(np.isfinite(ci)):
                    ax.fill_between(x, y - ci, y + ci, alpha=.14, color=COLORS[alg])
            ax.axvline(12, color='black', linestyle='--', label='Distance changes at 12 s')
            ax.set(xlabel='Time since UDP start (s)', ylabel=LABELS['goodput_mbps'],
                   title=f'Step {direction} m; mean and 95% CI per 0.25 s bin')
            ax.grid(alpha=.22); ax.legend(); save(fig, 'step-goodput-' + direction)
            # Mechanism view: first run only, not an average of switching times.
            representative = min(int(r['run']) for r in step)
            fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, layout='constrained')
            for alg in COLORS:
                row = next(r for r in step if r['config_label'] == direction and
                           r['algorithm'] == alg and int(r['run']) == representative)
                with (src / (row['case_id'] + '-rates.csv')).open(newline='') as f:
                    rates = list(csv.DictReader(f))
                with (src / (row['case_id'] + '-state.csv')).open(newline='') as f:
                    states = list(csv.DictReader(f))
                if rates:
                    axes[0].step([float(r['time_s']) - 2 for r in rates] + [24],
                                 [float(r['selected_data_rate_mbps']) for r in rates]
                                 + [float(rates[-1]['selected_data_rate_mbps'])], where='post',
                                 label=alg, color=COLORS[alg])
                # Thresholds have different units, so AMRR is kept out of the AARF threshold panel.
                if alg != 'AMRR':
                    x, y = [], []
                    for r in states:
                        point = float(r['success_threshold'])
                        if not y or point != y[-1]:
                            x.append(float(r['time_s']) - 2); y.append(point)
                    if x:
                        axes[1].step(x + [24], y + [y[-1]], where='post', label=alg, color=COLORS[alg])
            for ax in axes:
                ax.axvline(12, color='black', linestyle='--'); ax.grid(alpha=.22); ax.legend()
                ax.set_xlim(0, 24)
            axes[0].set_ylabel('Selected TX-vector rate (Mb/s)')
            axes[1].set(ylabel='ARF/AARF success threshold', xlabel='Time since UDP start (s)')
            save(fig, 'step-trace-' + direction + f'-run{representative}')

    readme = f'''# Kết quả phân tích

Đã xác minh {len(rows)} lần chạy từ các summary và timeseries riêng, đối chiếu plan.json.
Đồ thị và bảng chỉ sử dụng những lần chạy đó. CI là Student-t 95% cấp run.
CI theo bin thời gian là CI riêng từng bin, không phải dải tin cậy đồng thời cho cả đường.

- aggregate.csv: trung bình, n và nửa độ rộng CI cho mỗi cấu hình.
- rts-on-minus-off.csv: RTS bật trừ RTS tắt, ghép theo thuật toán, khoảng cách, seed/run.
- sensitivity-minus-baseline.csv: cấu hình quét trừ cấu hình mặc định; mỗi lần đổi một tham số.
- best-fixed-mode.csv: mode có mean goodput cao nhất trong tám mode đã đo tại mỗi d.
  Maximum fixed mean là đường tham khảo từ dữ liệu ở cùng tải; việc chọn giá trị lớn nhất
  từ mẫu không tạo ra một cận trên lý thuyết hay một mô hình RBAR.
- step-phases-aggregate.csv: goodput của gói ĐẾN trong từng cửa sổ thời gian.
  Gói tạo trước lúc đổi kênh có thể đến sau đó; backlog là một phần của kết quả tải này.
  Các cửa sổ 2 s / 4 s là quy ước đo, không tự động chứng minh đã hội tụ.
- step-trace*: một run đại diện; rate là giá trị chọn TX vector, không phải PHY airtime.

PDR là tỷ lệ 0–1 trong CSV, được đổi thành % trên hình. Chênh lệch PDR trong CSV
vẫn là tỷ lệ; nhân 100 để được điểm phần trăm. Delay tính trên gói nhận trong toàn
cửa sổ; tệp phase chỉ cung cấp goodput, không suy ra phase PDR/delay.
'''
    (out / 'DOC_KET_QUA.md').write_text(readme, encoding='utf-8')
    print(f'PASS: analyzed {len(rows)} simulations -> {out}')


if __name__ == '__main__':
    main()
