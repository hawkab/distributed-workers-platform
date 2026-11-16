#!/usr/bin/env python3
"""Run as root on the dedicated fleet host, after its containers are ready.

No existing AgentFactory databases, queues or consumers are used here.
Secrets are generated only under /etc/fleet-worker-gateway, never in the repo.
"""
import argparse
import json
import os
import re
from pathlib import Path
import secrets
import subprocess


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'deployment.local.json')
parser.add_argument('--check', action='store_true', help='Validate local configuration without changing the host')
args = parser.parse_args()
try:
    deployment = json.loads(args.config.read_text())
    public_host = deployment['public_host']
except (OSError, ValueError, KeyError, TypeError):
    parser.error('A private deployment configuration file with public_host is required')
if not isinstance(public_host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', public_host):
    parser.error('Invalid public_host in private deployment configuration')
state_directory = Path('/var/lib/fleet-worker-gateway')
artifact_value = deployment.get('artifact_dir', str(state_directory / 'artifacts'))
if not isinstance(artifact_value, str) or not Path(artifact_value).is_absolute() or any(c in artifact_value for c in '\x00\r\n'):
    parser.error('artifact_dir must be a dedicated absolute persistent directory')
artifact_directory = Path(artifact_value).resolve()
if artifact_directory == Path('/'):
    parser.error('artifact_dir must be a dedicated absolute persistent directory')
# EnvironmentFile supports quoted values. Unit path specifiers need literal %%.
artifact_environment_value = json.dumps(str(artifact_directory), ensure_ascii=False)
artifact_unit_path = json.dumps(str(artifact_directory).replace('%', '%%'), ensure_ascii=False)
if args.check:
    print('Private deployment configuration is valid.')
    raise SystemExit(0)
assert os.geteuid() == 0
root = Path('/etc/fleet-worker-gateway')
root.mkdir(mode=0o700, exist_ok=True)
secret_path = root / 'bootstrap.json'
config = json.loads(secret_path.read_text()) if secret_path.exists() else {}
for key in ('pg_password', 'mq_password', 'admin_token', 'runtime_pg_password'):
    config.setdefault(key, secrets.token_hex(32))
secret_path.write_text(json.dumps(config, indent=2) + '\n')
secret_path.chmod(0o600)

# This is the isolated fleet-postgres instance, not the main platform database.
sql = """
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='fleet_gateway') THEN
  CREATE ROLE fleet_gateway LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
 END IF;
END $$;
ALTER ROLE fleet_gateway PASSWORD '%s';
CREATE SCHEMA IF NOT EXISTS worker_fleet AUTHORIZATION fleet_gateway;
GRANT CONNECT ON DATABASE fleet_workers TO fleet_gateway;
""" % config['runtime_pg_password']
run('docker', 'exec', '-i', 'fleet-postgres', 'psql', '-U', 'fleet_workers',
    '-d', 'fleet_workers', '-v', 'ON_ERROR_STOP=1', input=sql.encode(),
    stdout=subprocess.DEVNULL)
if subprocess.run(['id', 'fleetworker'], stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL).returncode:
    run('useradd', '--system', '--home-dir', '/var/lib/fleet-worker-gateway',
        '--shell', '/usr/sbin/nologin', 'fleetworker')

environment = root / 'gateway.env'
environment.write_text(
    'DATABASE_URL=postgres://fleet_gateway:' + config['runtime_pg_password'] +
    '@127.0.0.1:15446/fleet_workers?sslmode=disable\n' +
    'WORKER_ADMIN_TOKEN=' + config['admin_token'] + '\n' +
    'WORKER_AMQP_URL=amqp://fleet_events:' + config['mq_password'] +
    '@127.0.0.1:15673/fleet-workers\n' +
    'WORKER_BIND=127.0.0.1:18220\n' +
    'WORKER_RELEASE_DIR=/var/lib/fleet-worker-gateway/releases\n' +
    'WORKER_ARTIFACT_DIR=' + artifact_environment_value + '\n')
environment.chmod(0o600)
for directory in (state_directory, state_directory / 'releases', artifact_directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    run('chown', 'fleetworker:fleetworker', str(directory))
run('chown', '-R', 'fleetworker:fleetworker', '/var/lib/fleet-worker-gateway/releases')

Path('/etc/systemd/system/fleet-worker-gateway.service').write_text('''[Unit]
Description=Dedicated distributed worker gateway
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=fleetworker
Group=fleetworker
EnvironmentFile=/etc/fleet-worker-gateway/gateway.env
StateDirectory=fleet-worker-gateway
StateDirectoryMode=0700
ReadWritePaths=/var/lib/fleet-worker-gateway @ARTIFACT_DIR@
ExecStart=/opt/fleet-worker-gateway/worker-gateway
TimeoutStopSec=infinity
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
UMask=0077

[Install]
WantedBy=multi-user.target
'''.replace('@ARTIFACT_DIR@', artifact_unit_path))

Path('/etc/nginx/sites-available/fleet-worker-gateway.conf').write_text('''server {
 listen 80;
 server_name @PUBLIC_HOST@;
 location ^~ /.well-known/acme-challenge/ { root /var/www/fleet-worker-acme; }
 location / { return 301 https://$host$request_uri; }
}
server {
 listen 443 ssl;
 server_name @PUBLIC_HOST@;
 ssl_certificate /etc/fleet-worker-gateway/acme/live/@PUBLIC_HOST@/fullchain.pem;
 ssl_certificate_key /etc/fleet-worker-gateway/acme/live/@PUBLIC_HOST@/privkey.pem;
 ssl_protocols TLSv1.2 TLSv1.3;
 # Match Go net/http DefaultMaxHeaderBytes; resource profiles are not truncated.
 large_client_header_buffers 4 1m;
 location /git/ {
  proxy_pass http://127.0.0.1:18300/;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-For $remote_addr;
  client_max_body_size 512m;
 }
 # Binary upload bodies bypass the JSON budget and nginx temporary files.
 location ~ ^/fleet/v1/artifacts/[0-9a-fA-F-]+/chunks/[0-9]+$ {
  rewrite ^/fleet(/.*)$ $1 break;
  proxy_pass http://127.0.0.1:18220;
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-For $remote_addr;
  client_max_body_size 0;
  proxy_request_buffering off;
  proxy_buffering off;
  proxy_max_temp_file_size 0;
  proxy_read_timeout 90s;
  proxy_send_timeout 90s;
  gzip off;
 }
 # Device-scoped and administrator downloads are both streamed unchanged.
 location ~ ^/fleet/v1/(admin/)?artifacts/[0-9a-fA-F-]+/content$ {
  rewrite ^/fleet(/.*)$ $1 break;
  proxy_pass http://127.0.0.1:18220;
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-For $remote_addr;
  client_max_body_size 16m;
  proxy_buffering off;
  proxy_max_temp_file_size 0;
  proxy_read_timeout 90s;
  proxy_send_timeout 90s;
  gzip off;
 }
 location /fleet/ {
  proxy_pass http://127.0.0.1:18220/;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-For $remote_addr;
  client_max_body_size 16m;
  proxy_read_timeout 90s;
 }
 location / { return 404; }
}
'''.replace('@PUBLIC_HOST@', public_host))
link = Path('/etc/nginx/sites-enabled/fleet-worker-gateway.conf')
if not link.exists():
    link.symlink_to('/etc/nginx/sites-available/fleet-worker-gateway.conf')
Path('/etc/systemd/system/fleet-certificate-renew.service').write_text('''[Unit]
Description=Renew dedicated worker HTTPS certificate
[Service]
Type=oneshot
ExecStart=/opt/fleet-certbot/bin/certbot renew --quiet --config-dir /etc/fleet-worker-gateway/acme --work-dir /var/lib/fleet-worker-gateway/acme --logs-dir /var/log/fleet-worker-gateway-acme --deploy-hook "systemctl reload nginx"
''')
Path('/etc/systemd/system/fleet-certificate-renew.timer').write_text('''[Unit]
Description=Check dedicated worker certificate daily
[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true
[Install]
WantedBy=timers.target
''')
run('nginx', '-t')
run('systemctl', 'daemon-reload')
run('systemctl', 'enable', '--now', 'fleet-certificate-renew.timer')
run('systemctl', 'reload', 'nginx')
print('Dedicated fleet configuration ready; secret values withheld.')
