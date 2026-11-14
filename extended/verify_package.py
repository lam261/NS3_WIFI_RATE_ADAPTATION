#!/usr/bin/env python3
"""Test orchestration/measurement helpers using temporary SYNTHETIC fixtures, not ns-3 results."""
import csv
import json
import pathlib
import struct
import tempfile
import unittest
from run_suite import make_cases, variants, check_case
from analyze_suite import phase_mean, paired
from check_smoke import count_frames


def fixture(directory, case, received=4800):
    o = case['options']
    mapping = dict(algorithm='algorithm', scenario='scenario', distance='distance_m',
                   nearDistance='near_m', farDistance='far_m', switchTime='switch_s', rts='rts',
                   paperRates='paper_rates', seed='seed', run='run', duration='duration_s',
                   packetSize='packet_size', packets='planned_packets', interval='interval_s',
                   txPower='tx_power_dbm', noiseFigure='noise_figure_db', exponent='exponent',
                   referenceLoss='reference_loss_db', minSuccess='min_success', maxSuccess='max_success',
                   minTimeout='min_timeout', successK='success_k', timeoutK='timeout_k',
                   amrrPeriod='amrr_period_s', fixedMode='fixed_mode')
    row = {v: o[k] for k, v in mapping.items()}
    row.update(tx_packets=o['packets'], rx_packets=received,
               goodput_mbps=received * o['packetSize'] * 8 / o['duration'] / 1e6,
               pdr=received/o['packets'], mean_delay_ms=1,
               data_failed_callbacks=0, final_data_failed_callbacks=0,
               offered_mbps=o['packetSize'] * 8 / o['interval'] / 1e6)
    prefix = directory / case['case_id']
    with pathlib.Path(str(prefix) + '-summary.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(row)); w.writeheader(); w.writerow(row)
    n = round(o['duration'] / o['sample'])
    with pathlib.Path(str(prefix) + '-timeseries.csv').open('w', newline='') as f:
        w = csv.writer(f); w.writerow(['time_s', 'goodput_mbps'])
        for k in range(1, n + 1):
            packets = received // n + int(k <= received % n)
            w.writerow([2 + k * o['sample'], packets * o['packetSize'] * 8 / o['sample'] / 1e6])
    pathlib.Path(str(prefix) + '-rates.csv').write_text('time_s,selected_data_rate_mbps\n2,6\n3,18\n')
    pathlib.Path(str(prefix) + '-state.csv').write_text(
        'time_s,rate_index,success_threshold,timer,retry,recovery\n2,0,10,0,0,0\n')
    pathlib.Path(str(prefix) + '-done.json').write_text(json.dumps(case))
    return row


class Checks(unittest.TestCase):
    def test_plans(self):
        expected = dict(smoke=6, step=60, rts=300, fixed=550, sensitivity=240, all=1150)
        for suite, count in expected.items():
            cases = make_cases(suite)
            self.assertEqual(len(cases), count)
            self.assertEqual(len({c['case_id'] for c in cases}), count)
            self.assertTrue(all(11 <= c['options']['run'] <= 20 for c in cases))
        self.assertEqual(len(variants()), 12)
        baseline = variants()[0][1]
        for _, options in variants()[1:]:
            self.assertEqual(sum(options[k] != baseline[k] for k in options), 1)
        self.assertEqual({c['options']['fixedMode'] for c in make_cases('fixed', runs=1)
                          if c['options']['algorithm'] == 'Fixed'},
                         {f'OfdmRate{r}Mbps' for r in (6, 9, 12, 18, 24, 36, 48, 54)})

    def test_summary_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp); case = make_cases('smoke')[0]
            fixture(directory, case)
            self.assertEqual(int(check_case(directory, case)['rx_packets']), 4800)
            other = json.loads(json.dumps(case)); other['options']['rts'] = 1
            with self.assertRaises(ValueError): check_case(directory, other)
            file = directory / (case['case_id'] + '-timeseries.csv')
            file.write_text('\n'.join(file.read_text().splitlines()[:-1]) + '\n')
            with self.assertRaises(ValueError): check_case(directory, case)

    def test_phase_boundary(self):
        series = [dict(time_s=2+i*.25, goodput_mbps=8 if i <= 8 else 16) for i in range(1, 17)]
        self.assertEqual(phase_mean(series, 0, 2), 8)
        self.assertEqual(phase_mean(series, 2, 4), 16)
        with self.assertRaises(ValueError): phase_mean(series, .1, 2)

    def test_paired_arms(self):
        rows = [dict(distance_m='40', rts=arm, seed='1', run=str(run),
                     goodput_mbps=10+int(arm)*2+run)
                for run in (1, 2, 3) for arm in ('0', '1')]
        result = paired(rows, ['distance_m'], 'rts', '1', '0', ['goodput_mbps'])
        self.assertEqual(result[0]['goodput_mbps_n'], 3)
        self.assertEqual(result[0]['goodput_mbps_mean'], 2)
        self.assertEqual(result[0]['goodput_mbps_ci95'], 0)

    def test_radiotap_pcap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'fixture.pcap'
            with path.open('wb') as f:
                f.write(struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 127))
                for fc in (0xb4, 0xc4, 0xd4, 0x08):
                    frame = b'\x00\x00\x08\x00\x00\x00\x00\x00' + bytes([fc, 0]) + b'\x00'*22
                    f.write(struct.pack('<IIII', 0, 0, len(frame), len(frame))); f.write(frame)
            self.assertEqual(count_frames(path), dict(RTS=1, CTS=1, ACK=1, DATA=1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
