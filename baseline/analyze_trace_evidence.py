#!/usr/bin/env python3
"""Validate copied main results and extract mechanism evidence from run-1 traces."""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

RATES = [6, 12, 18, 36, 54]
COLORS = {'ARF': '#2563a6', 'AARF': '#d76b14', 'AMRR': '#16805d'}


def read(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def changes(rows, key):
    result = []
    old = None
    for row in rows:
        value = int(row[key])
        if value != old:
            result.append((float(row['time_s']) - 2, value))
            old = value
    return result


def hold_points(points, end):
    times = [p[0] for p in points]
    values = [p[1] for p in points]
    if times and times[-1] < end:
        times.append(end)
        values.append(values[-1])
    return times, values


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from scipy.stats import t
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    raw = read(args.input / 'all-runs.csv')
    aggregates = read(args.input / 'aggregate.csv')
    paired = read(args.input / 'paired-aarf-minus-arf.csv')
    assert len(raw) == 150 and len(aggregates) == 15 and len(paired) == 5
    groups = defaultdict(list)
    for row in raw:
        assert row['scenario'] == 'static' and row['rts'] == '0'
        assert int(row['rx_packets']) <= int(row['tx_packets'])
        expected = int(row['rx_packets']) * int(row['packet_size']) * 8 / float(row['duration_s']) / 1e6
        assert math.isclose(float(row['goodput_mbps']), expected, abs_tol=1e-8)
        groups[row['algorithm'], row['distance_m']].append(row)
    for group in groups.values():
        assert len(group) == 10
        assert len({(r['seed'], r['run']) for r in group}) == 10
    for row in aggregates:
        group = groups[row['algorithm'], row['distance_m']]
        for metric in ['goodput_mbps', 'pdr', 'mean_delay_ms',
                       'data_failed_callbacks', 'final_data_failed_callbacks']:
            values = [float(r[metric]) for r in group]
            mean = statistics.mean(values)
            half = float(t.ppf(.975, 9)) * statistics.stdev(values) / math.sqrt(10)
            assert math.isclose(float(row[metric+'_mean']), mean, rel_tol=1e-8, abs_tol=1e-8)
            assert math.isclose(float(row[metric+'_ci95']), half, rel_tol=1e-8, abs_tol=1e-8)
    for row in paired:
        first = {(r['seed'], r['run']): float(r['goodput_mbps'])
                 for r in groups['ARF', row['distance_m']]}
        second = {(r['seed'], r['run']): float(r['goodput_mbps'])
                  for r in groups['AARF', row['distance_m']]}
        differences = [second[k] - first[k] for k in first]
        assert math.isclose(statistics.mean(differences), float(row['delta_mbps_mean']), abs_tol=1e-8)
        half = float(t.ppf(.975, 9)) * statistics.stdev(differences) / math.sqrt(10)
        assert math.isclose(half, float(row['delta_mbps_ci95']), abs_tol=1e-8)

    evidence = {'validation': 'PASS: 150 runs, 15 groups, 10 unique RNG pairs per group, '
                              'goodput definitions, aggregate means/CIs and paired CIs',
                'window_s': [2, 26], 'traces': {}}
    data = {}
    for alg in COLORS:
        summary, = read(args.input / f'{alg}-summary.csv')
        assert summary['distance_m'] == '40' and summary['seed'] == '1' and summary['run'] == '1'
        state = [r for r in read(args.input / f'{alg}-state.csv') if 2 <= float(r['time_s']) < 26]
        rates = [r for r in read(args.input / f'{alg}-rates.csv') if 2 <= float(r['time_s']) < 26]
        series = read(args.input / f'{alg}-timeseries.csv')
        assert math.isclose(sum(float(r['goodput_mbps']) for r in series) / 24,
                            float(summary['goodput_mbps']), abs_tol=1e-8)
        base_changes = changes(state, 'rate_index')
        threshold_changes = changes(state, 'success_threshold')
        failed_probe = 0
        upgrades = 0
        previous = {'rate_index': '0', 'retry': '0', 'recovery': '0'}
        for row in state:
            old, new = int(previous['rate_index']), int(row['rate_index'])
            if old == 2 and new == 3 and row['recovery'] == '1' and row['retry'] == '0':
                upgrades += 1
            if (old == 3 and new == 2 and previous['recovery'] == '1'
                    and previous['retry'] == '0' and row['retry'] == '1'):
                failed_probe += 1
            previous = row
        result = {'summary': summary, 'threshold_changes_since_start_s': threshold_changes,
                  'base_rate_changes_since_start_s': [(tm, RATES[index]) for tm, index in base_changes]}
        if alg in ['ARF', 'AARF']:
            assert upgrades == failed_probe == int(summary['data_failed_callbacks'])
            result['upgrades_18_to_36'] = upgrades
            result['failed_first_probe_36_to_18'] = failed_probe
            probe_times = [tm for tm, index in base_changes if index == 3 and tm > 1]
            result['mean_probe_interval_after_1s_ms'] = statistics.mean(
                (b-a)*1000 for a,b in zip(probe_times, probe_times[1:]))
        evidence['traces'][alg] = result
        data[alg] = (summary, state, rates, series)
    reduction = 100 * (1 - evidence['traces']['AARF']['failed_first_probe_36_to_18'] /
                       evidence['traces']['ARF']['failed_first_probe_36_to_18'])
    evidence['failed_probe_reduction_percent_run1'] = reduction

    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})

    def save(fig, name):
        fig.savefig(args.out / (name+'.png'), dpi=180)
        fig.savefig(args.out / (name+'.svg'))
        plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(9, 7.5), sharex=True, layout='constrained')
    for ax, alg in zip(axes[:2], ['ARF', 'AARF']):
        points = [(float(r['time_s'])-2, float(r['selected_data_rate_mbps']))
                  for r in data[alg][2]]
        # Include just the first point beyond the zoom boundary to preserve the last step.
        clipped = [p for p in points if p[0] <= .36]
        xs, ys = hold_points(clipped, .35)
        ax.step(xs, ys, where='post', color=COLORS[alg], linewidth=1.4)
        ax.set_ylabel(f'{alg}\nSelected rate (Mb/s)')
        ax.set_yticks([6, 12, 18, 36])
        ax.set_ylim(3, 40)
        ax.grid(alpha=.2)
    for alg in ['ARF', 'AARF']:
        points = evidence['traces'][alg]['threshold_changes_since_start_s']
        xs, ys = hold_points(points, .35)
        axes[2].step(xs, ys, where='post', label=alg, color=COLORS[alg])
    axes[2].set(xlabel='Time since traffic start (s)', ylabel='Success threshold\n(transmissions)',
                xlim=(0, .35), ylim=(0, 57))
    axes[2].legend(ncol=2)
    axes[2].grid(alpha=.2)
    axes[0].set_title('ARF / AARF: failed 36 Mb/s probes and threshold backoff\n40 m, seed=1, run=1; TX-vector selection trace')
    save(fig, 'aarf-mechanism-40m')

    fig, axes = plt.subplots(3, 1, figsize=(10, 7.8), sharex=True, layout='constrained')
    for alg in COLORS:
        rows = data[alg][3]
        axes[0].plot([float(r['time_s'])-2 for r in rows],
                     [float(r['goodput_mbps']) for r in rows], marker='.',
                     label=alg, color=COLORS[alg], linewidth=1.3)
    axes[0].set_ylabel('UDP goodput\n(Mb/s; 1 s bins)')
    axes[0].legend(ncol=3, loc='lower right')
    base = evidence['traces']['AMRR']['base_rate_changes_since_start_s']
    xs, ys = hold_points(base, 24)
    axes[1].step(xs, ys, where='post', color=COLORS['AMRR'])
    axes[1].set_ylabel('AMRR base r0\n(Mb/s)')
    axes[1].set_yticks([6, 12, 18, 36])
    xs, ys = hold_points(evidence['traces']['AMRR']['threshold_changes_since_start_s'], 24)
    axes[2].step(xs, ys, where='post', color=COLORS['AMRR'])
    axes[2].set_ylabel('AMRR threshold\n(success periods)')
    axes[2].set_yticks([1, 2, 4, 8, 15])
    axes[2].set_xlabel('Time since traffic start (s)')
    for i,(begin, rate) in enumerate(base):
        end = base[i+1][0] if i+1 < len(base) else 24
        if rate == 36:
            for ax in axes:
                ax.axvspan(begin, end, color='#ce5360', alpha=.13)
    for ax in axes:
        ax.set_xlim(0,24)
        ax.grid(alpha=.2)
    axes[0].set_title('AMRR: recurring high-rate trials after startup\n40 m, seed=1, run=1; shaded intervals: base r0 = 36 Mb/s')
    save(fig, 'amrr-mechanism-40m')

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), layout='constrained')
    for alg in COLORS:
        rows = sorted([r for r in aggregates if r['algorithm']==alg], key=lambda r:float(r['distance_m']))
        x = [float(r['distance_m']) for r in rows]
        for ax,metric,scale in zip(axes, ['goodput_mbps', 'pdr', 'mean_delay_ms'], [1,100,1]):
            ax.errorbar(x, [float(r[metric+'_mean'])*scale for r in rows],
                        yerr=[float(r[metric+'_ci95'])*scale for r in rows],
                        marker='o', capsize=3, color=COLORS[alg], label=alg)
    for ax,label in zip(axes,['UDP goodput (Mb/s)','PDR within window (%)','Mean received-packet delay (ms)']):
        ax.set(xlabel='Distance (m)',ylabel=label)
        ax.grid(alpha=.2)
    axes[0].legend()
    fig.suptitle('ns-3.45 static experiments, RTS off; mean and 95% t CI, 10 runs/condition')
    save(fig, 'main-static-345')

    (args.out/'trace-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    report = ['# Phân tích trace tại 40 m và kiểm tra dữ liệu chính', '',
              'Ngày phân tích: 14/11/2026. Nguồn: dữ liệu thật do người dùng chép vào results-main-345. '
              'Trace đại diện có seed=1, run=1, RTS tắt; cửa sổ đo tuyệt đối [2,26) s. '
              'Các thời điểm dưới đây tính từ lúc bắt đầu gửi UDP.', '',
              '## Kiểm tra tính nhất quán dữ liệu', '', evidence['validation'], '',
              'Đã tính lại mean và CI cho goodput, PDR, delay, callback lỗi từ 150 dòng raw; '
              'đối chiếu 15 dòng aggregate và 5 CI ghép cặp. Tổng 24 bin goodput của mỗi trace '
              'khớp goodput trong summary.', '',
              '## ARF và AARF: cơ chế được quan sát trực tiếp', '',
              '| Chỉ số, cùng một run | ARF | AARF |', '|---|---:|---:|']
    for label,key in [('Probe tăng từ 18 lên 36 Mb/s','upgrades_18_to_36'),
                      ('Probe đầu tiên thất bại, quay về 18 Mb/s','failed_first_probe_36_to_18'),
                      ('Khoảng giữa các probe sau giây thứ nhất, trung bình (ms)','mean_probe_interval_after_1s_ms')]:
        report.append(f"| {label} | {evidence['traces']['ARF'][key]:.3f} | {evidence['traces']['AARF'][key]:.3f} |")
    report += ['', f'AARF giảm {reduction:.2f}% số probe thất bại so với ARF trong trace đại diện này. '
               'Đây là tỷ lệ theo một run, không phải trung bình hay CI trên 10 run.', '',
               'ARF giữ ngưỡng thành công bằng 10. AARF đổi ngưỡng sang 20 tại t=0.07270 s, '
               '40 tại t=0.09782 s và chặn ở 50 tại t=0.14710 s. Các chuyển trạng thái này '
               'đi cùng lần đầu thử 36 Mb/s thất bại, quay về 18 Mb/s và retry=1. '
               'Trace vì vậy hỗ trợ cách giải thích: backoff làm probe thưa hơn, giảm số lần '
               'thử rate cao không thành công, phù hợp với goodput AARF cao hơn. '
               'Chưa có PHY airtime/PCAP để định lượng thời gian chiếm kênh tiết kiệm được.', '',
               '![AARF mechanism](aarf-mechanism-40m.png)', '',
               '## AMRR: không chỉ có ảnh hưởng khởi động', '',
               'AMRR chọn 6 Mb/s lúc t≈0.00944 s, lên 12 tại 1.00952 s và 18 tại 2.01017 s. '
               'Các đợt thử base r0=36 Mb/s nằm gần [3.011,4.012], [6.013,7.014], '
               '[11.017,12.018] và [20.024,21.025] s. Mỗi đợt kéo dài xấp xỉ một chu kỳ '
               'cập nhật, trong khi mỗi packet có thể fallback từ 36 về 18 Mb/s. '
               'Ngưỡng số chu kỳ thành công tăng 1→2→4→8→15 sau các đợt thử không đạt.', '',
               'Goodput trong các bin kết thúc ở giây 4, 7, 12 và 21 lần lượt là '
               '9.307872, 9.307872, 9.344160 và 9.362304 Mb/s; nhiều bin ở giữa đạt gần '
               '14.9–15.0 Mb/s. Các đợt giảm sau nhiều giây cho thấy ảnh hưởng không chỉ '
               'đến từ bước tăng rate lúc khởi động. Chưa có queue trace để tách phần delay '
               'do mỗi cơ chế; không quy toàn bộ delay khoảng 2 s của AMRR cho startup.', '',
               '![AMRR mechanism](amrr-mechanism-40m.png)', '',
               '## Cách dùng hình và giới hạn', '',
               '- Hình main-static-345 sử dụng 10 run/cấu hình, CI của từng chỉ số mean. '
               'Hình trace minh họa đúng một run, không có CI.',
               '- rates.csv ghi các lần thay đổi TX-vector selection, không phải mọi lần phát '
               'PHY. rate_index trong AMRR state là base r0, khác rate thực được chọn cho retry.',
               '- Ngưỡng AARF đếm số lần truyền thành công liên tiếp; ngưỡng AMRR đếm chu kỳ. '
               'Các hình mới tách hai đại lượng để không gây hiểu nhầm về đơn vị.',
               '- Cả ba trace có final_data_failed_callbacks=0 nhưng PDR < 1. '
               'Điều này bác bỏ cách quy toàn bộ UDP chưa nhận thành các frame đã hết retry; '
               'chưa phân rã được gói bị loại ở hàng đợi, ARP và gói nhận ngoài cửa sổ.',
               '- Adapter AMRR cập nhật khi lấy TX vector sau deadline, có thể đang ở giữa '
               'retry của một packet. Đây không phải mô phỏng đầy đủ descriptor/FIFO của AR5212. '
               'Ví dụ tại t≈12.0176 s, base giảm trong lúc retry=1 nên có lần chọn 12 Mb/s ngắn.', '',
               '## Đoạn nhận xét có thể đưa vào báo cáo', '',
               'Trace tại khoảng cách 40 m với seed=1 và run=1 cho thấy ARF thường xuyên thử '
               'tăng từ 18 lên 36 Mb/s rồi fallback, trong khi AARF điều chỉnh ngưỡng thành '
               'công từ 10 lên 20, 40 và tối đa 50. Số probe thất bại giảm từ 1862 ở ARF '
               'xuống 392 ở AARF, tương đương khoảng 78.95% trong run đại diện. Quan sát này '
               'hỗ trợ cơ chế giải thích cho mức tăng goodput khoảng 4.94% đã được đo trong '
               'batch 10 run. Với AMRR, các đợt tăng base rate lên 36 Mb/s kéo dài xấp xỉ '
               'một giây và trùng với các bin goodput giảm xuống khoảng 9.3 Mb/s; các đợt này '
               'còn xuất hiện sau giai đoạn khởi động. Kết quả cần được hiểu trong phạm vi '
               'mô hình và adapter AMRR đã mô tả, chưa suy rộng sang driver và phần cứng thực.', '',
               '![Main static results](main-static-345.png)']
    (args.out/'PHAN_TICH_TRACE_40M.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    print(evidence['validation'])
    print(f'Failed probes ARF=1862, AARF=392; reduction={reduction:.6f}%')
    print('Wrote figures, evidence JSON and report:', args.out)


if __name__ == '__main__':
    main()
