"""Approve one known camera IP/port without replacing other .env settings."""
import argparse
from datetime import datetime
import ipaddress
import os
from pathlib import Path
import shutil
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    try:
        ip = ipaddress.ip_address(args.ip)
        if ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified or getattr(ip, 'ipv4_mapped', None):
            raise ValueError()
        if not 1 <= args.port <= 65535:
            raise ValueError()
    except ValueError:
        raise SystemExit('Provide a valid camera IP and numeric port from 1 to 65535.') from None
    root = Path(__file__).resolve().parents[1]
    path = root/'backend/.env'
    if not path.is_file():
        raise SystemExit('Existing backend/.env is required.')
    from dotenv import dotenv_values
    # Read the file, not stale shell overrides, for the persistent allowlist.
    values = dotenv_values(path)
    nets = [x.strip() for x in (values.get('CAMERA_ALLOW_CIDRS') or '').split(',') if x.strip()]
    ports = [x.strip() for x in (values.get('CAMERA_PORTS') or '554,8554').split(',') if x.strip()]
    try:
        if not any(ip in ipaddress.ip_network(net) for net in nets):
            nets.append(f'{ip}/{ip.max_prefixlen}')
        ports = [str(int(p)) for p in ports]
        if any(not 1 <= int(p) <= 65535 for p in ports):raise ValueError()
    except ValueError:
        raise SystemExit('Existing camera allowlist is invalid. Correct it locally before retrying.') from None
    ports.append(str(args.port))
    changes = {'CAMERA_ALLOW_CIDRS':','.join(dict.fromkeys(nets)), 'CAMERA_PORTS':','.join(dict.fromkeys(ports))}
    original = path.read_text(encoding='utf-8-sig')
    lines, seen = [], set()
    for line in original.splitlines():
        key = line.partition('=')[0].strip()
        if key in changes:
            if key not in seen:lines.append(key+'='+changes[key]);seen.add(key)
        else:lines.append(line)
    lines.extend(key+'='+value for key,value in changes.items() if key not in seen)
    backup = path.with_name('.env.camera-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path, backup)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.camera-',delete=False) as output:
            temp=Path(output.name);output.write('\n'.join(lines)+'\n');output.flush();os.fsync(output.fileno())
        os.replace(temp,path)
    finally:
        if temp and temp.exists():temp.unlink()
    print(f'Approved camera {ip}, port {args.port}. Other configuration preserved.')
    print('A private .env backup was created. Restart the backend; do not share the backup.')


if __name__ == '__main__':
    main()
