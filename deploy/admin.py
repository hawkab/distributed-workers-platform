#!/usr/bin/env python3
"""Administrative client executed on the fleet host. Never prints credentials."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

p = argparse.ArgumentParser()
p.add_argument('method', choices=('GET', 'POST', 'PATCH'))
p.add_argument('path', help='API path beginning /v1/admin/')
p.add_argument('--body-file', type=Path)
p.add_argument('--private-output', type=Path, help='Store a credential-bearing reply without printing it')
args = p.parse_args()
if not args.path.startswith('/v1/admin/'):
    p.error('Only administrative API paths are supported')
secret = json.loads(Path('/etc/fleet-worker-gateway/bootstrap.json').read_text())
body = args.body_file.read_bytes() if args.body_file else (sys.stdin.buffer.read() if args.method != 'GET' else None)
request = urllib.request.Request('http://127.0.0.1:18220' + args.path,
                                 data=body or None, method=args.method,
                                 headers={'Authorization': 'Bearer ' + secret['admin_token'],
                                          'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=30) as response:
    result = response.read()
if args.private_output:
    # Exclusive creation avoids accidentally overwriting the only device token.
    with args.private_output.open('xb') as out:
        args.private_output.chmod(0o600)
        out.write(result)
    print('Private response stored.')
else:
    value = json.loads(result)
    if isinstance(value, dict) and any(k.lower() in {'token', 'admin_token', 'password', 'secret', 'access_token'} for k in value):
        p.error('Credential-bearing response requires --private-output')
    print(json.dumps(value, ensure_ascii=False, indent=2))
