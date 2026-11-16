#!/usr/bin/env python3
"""Create only the dedicated fleet Docker resources; leave existing ones alone."""
import json
from pathlib import Path
import secrets
import subprocess


def call(*args, **kw):
    return subprocess.run(args, check=True, **kw)


def exists(kind, name):
    return subprocess.run(['docker', kind, 'inspect', name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


root = Path('/etc/fleet-worker-gateway')
root.mkdir(mode=0o700, exist_ok=True)
path = root / 'bootstrap.json'
secret = json.loads(path.read_text()) if path.exists() else {}
for key in ('pg_password', 'mq_password', 'admin_token'):
    secret.setdefault(key, secrets.token_hex(32))
path.write_text(json.dumps(secret, indent=2) + '\n')
path.chmod(0o600)
files = {
    'postgres.env': 'POSTGRES_DB=fleet_workers\nPOSTGRES_USER=fleet_workers\nPOSTGRES_PASSWORD=' + secret['pg_password'] + '\n',
    'rabbitmq.env': 'RABBITMQ_DEFAULT_USER=fleet_events\nRABBITMQ_DEFAULT_VHOST=fleet-workers\nRABBITMQ_DEFAULT_PASS=' + secret['mq_password'] + '\n',
    'rabbitmq.conf': 'listeners.tcp.default=5672\nvm_memory_high_watermark.absolute=192MiB\ndisk_free_limit.absolute=1GB\ndefault_queue_type=quorum\n',
}
for name, value in files.items():
    (root / name).write_text(value)
    (root / name).chmod(0o600 if name.endswith('.env') else 0o644)
if not exists('network', 'fleet-workers'):
    call('docker', 'network', 'create', 'fleet-workers')
for name in ('fleet-postgres-data', 'fleet-rabbitmq-data'):
    if not exists('volume', name):
        call('docker', 'volume', 'create', name)
common = ['docker', 'run', '-d', '--restart', 'unless-stopped', '--network', 'fleet-workers', '--cpu-shares', '128']
if not exists('container', 'fleet-postgres'):
    call(*common, '--name', 'fleet-postgres', '--memory', '512m',
         '--env-file', str(root / 'postgres.env'), '-p', '127.0.0.1:15446:5432',
         '-v', 'fleet-postgres-data:/var/lib/postgresql/data',
         'postgres@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24',
         '-c', 'shared_buffers=128MB', '-c', 'max_connections=30')
if not exists('container', 'fleet-rabbitmq'):
    call(*common, '--name', 'fleet-rabbitmq', '--memory', '384m',
         '--env-file', str(root / 'rabbitmq.env'), '-p', '127.0.0.1:15673:5672',
         '-v', 'fleet-rabbitmq-data:/var/lib/rabbitmq',
         '-v', str(root / 'rabbitmq.conf') + ':/etc/rabbitmq/rabbitmq.conf:ro',
         'rabbitmq@sha256:7fa20d0d23d63ed90499bbf62e24af48ec4ae5eb22d173f3db96e3f85b26884a')
for name in ('fleet-postgres', 'fleet-rabbitmq'):
    call('docker', 'start', name, stdout=subprocess.DEVNULL)
Path('/var/lib/fleet-worker-gateway/releases/android-stable').mkdir(parents=True, mode=0o750, exist_ok=True)
print('Dedicated fleet containers ready. Existing services untouched.')
