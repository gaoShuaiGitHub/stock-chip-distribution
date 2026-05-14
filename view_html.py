#!/usr/bin/env python3
with open('/Users/zhangyali/Documents/高帅事宜/量化/stock-chip-distribution/scripts/OKLO_chip.html', 'r') as f:
    lines = f.readlines()[:50]
    print(''.join(lines))