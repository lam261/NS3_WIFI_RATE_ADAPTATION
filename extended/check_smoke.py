#!/usr/bin/env python3
"""Validate six smoke runs and confirm RTS frames in native radiotap PCAP."""
import argparse
import json
import pathlib
import struct
from run_suite import check_case


def count_frames(path):
    counts = dict(RTS=0, CTS=0, ACK=0, DATA=0)
    with path.open('rb') as f:
        header = f.read(24)
        magic = header[:4]
        if magic in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1'):
            endian = '<'
        elif magic in (b'\xa1\xb2\xc3\xd4', b'\xa1\xb2\x3c\x4d'):
            endian = '>'
        else:
            raise ValueError(f'Unsupported/truncated PCAP header: {path}')
        if len(header) != 24 or struct.unpack(endian + 'I', header[20:24])[0] != 127:
            raise ValueError(f'Expected radiotap DLT 127: {path}')
        while True:
            record = f.read(16)
            if not record:
                break
            if len(record) != 16:
                raise ValueError('Truncated record header')
            size = struct.unpack(endian + 'IIII', record)[2]
            if size > 16 * 1024 * 1024:
                raise ValueError('Invalid capture record length')
            data = f.read(size)
            if len(data) != size or len(data) < 8:
                raise ValueError('Truncated radiotap frame')
            offset = struct.unpack('<H', data[2:4])[0]
            if offset < 8 or offset + 2 > len(data):
                raise ValueError('Invalid radiotap length')
            fc = data[offset] & 0xfc
            if fc == 0xb4: counts['RTS'] += 1
            elif fc == 0xc4: counts['CTS'] += 1
            elif fc == 0xd4: counts['ACK'] += 1
            elif (fc & 0x0c) == 0x08: counts['DATA'] += 1
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=pathlib.Path)
    a = p.parse_args()
    plan = json.loads((a.directory / 'plan.json').read_text())
    if len(plan['cases']) != 6 or any(c['suite'] != 'smoke' for c in plan['cases']):
        p.error('Expected a completed --suite smoke directory')
    for case in plan['cases']:
        marker = a.directory / (case['case_id'] + '-done.json')
        if not marker.exists() or json.loads(marker.read_text()) != case:
            raise ValueError('Smoke incomplete; resume the smoke batch')
        row = check_case(a.directory, case)
        if case['options']['pcap']:
            files = list(a.directory.glob(case['case_id'] + '-*.pcap'))
            if not files:
                raise ValueError('No PCAP generated')
            total = dict(RTS=0, CTS=0, ACK=0, DATA=0)
            for path in files:
                for k, v in count_frames(path).items(): total[k] += v
            if not total['DATA'] or (case['options']['rts'] and (not total['RTS'] or not total['CTS'])):
                raise ValueError(f'Expected DATA and RTS/CTS: {total}')
            if not case['options']['rts'] and total['RTS']:
                raise ValueError(f'Unexpected RTS when rts=0: {total}')
            print(case['config_label'], total, '(counts combine captures; not unique frames)')
        print(case['config_label'], 'UDP', row['rx_packets'], '/', row['tx_packets'])
    print('PASS: six smoke runs, complete measurements, correct RTS ON/OFF PCAP behavior')


if __name__ == '__main__':
    main()
