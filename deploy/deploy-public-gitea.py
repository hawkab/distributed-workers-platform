#!/usr/bin/env python3
"""Provision a separate public release mirror on an existing Docker/nginx host.

Run as root ON the target host. Existing Git/queue/database services are untouched.
Credentials are generated locally in --private-dir, never written to stdout.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

GITEA_IMAGE = "docker.gitea.com/gitea@sha256:aa90e8f00b755b0d665214ab9c14447ea44d3190dbe6b6d0cb46cd9c4f55d309"
RUNNER_IMAGE = "gitea/runner@sha256:874dff964c90017cb26a276938f4592937b8fc2b2f929eb14b2e0397bd14d874"
DEFAULT_JOB_IMAGE = "docker.gitea.com/runner-images@sha256:139605d4a6ab61e48dfd7687b11184881c2d7fcf06bf739e9cadb34f73deb51d"
REPOS = ("gateway", "worker-android", "protocol", "platform")


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        # Never render the command, stderr or argv: CLI credentials may be present.
        raise RuntimeError("Command failed: " + args[0])
    return result.stdout


def write_private(path, value):
    path.write_text(value)
    path.chmod(0o600)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True, help="Public HTTPS URL, including trailing subpath slash")
    p.add_argument("--nginx-vhost", required=True, type=Path)
    p.add_argument("--nginx-backup", required=True, type=Path, help="One existing/new backup file outside Git")
    p.add_argument("--private-dir", type=Path, default=Path("/etc/fleet-worker-gitea"))
    p.add_argument("--port", type=int, default=18300)
    p.add_argument("--organization", default="distributed-workers")
    p.add_argument("--admin", default="hawkab")
    p.add_argument("--job-image", default=DEFAULT_JOB_IMAGE)
    a = p.parse_args()
    u = urllib.parse.urlsplit(a.url)
    if u.scheme != "https" or not u.hostname or u.query or u.fragment or not u.path.endswith("/"):
        p.error("--url must be an HTTPS URL ending in a slash")
    prefix = u.path.rstrip("/")
    if not prefix or any(c not in "/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in prefix):
        p.error("Use a nonempty plain subpath, for example /git/")
    if os.geteuid() != 0:
        p.error("Run on the target host as root")
    os.umask(0o077)
    a.private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    a.private_dir.chmod(0o700)
    secret_file = a.private_dir / "bootstrap.json"
    if secret_file.exists():
        cfg = json.loads(secret_file.read_text())
    else:
        cfg = {"username": a.admin, "password": secrets.token_urlsafe(36), "url": a.url,
               "organization": a.organization}
        write_private(secret_file, json.dumps(cfg, indent=2))
    for image in (GITEA_IMAGE, RUNNER_IMAGE):
        run(["docker", "pull", image])
    exists = subprocess.run(["docker", "container", "inspect", "fleet-gitea"], capture_output=True).returncode == 0
    if not exists:
        cmd = ["docker", "run", "-d", "--name", "fleet-gitea", "--restart", "unless-stopped",
               "-p", f"127.0.0.1:{a.port}:3000", "-v", "fleet-gitea-data:/data"]
        env = {"USER_UID": "1000", "USER_GID": "1000", "GITEA__database__DB_TYPE": "sqlite3",
               "GITEA__database__PATH": "/data/gitea/gitea.db", "GITEA__server__ROOT_URL": a.url,
               "GITEA__server__DOMAIN": u.hostname, "GITEA__server__PROTOCOL": "http",
               "GITEA__server__HTTP_PORT": "3000", "GITEA__server__DISABLE_SSH": "true",
               "GITEA__security__INSTALL_LOCK": "true", "GITEA__service__DISABLE_REGISTRATION": "true",
               "GITEA__service__REQUIRE_SIGNIN_VIEW": "false", "GITEA__actions__ENABLED": "true",
               "GITEA__repository__DEFAULT_PRIVATE": "public",
               "GITEA__repository__DEFAULT_REPO_UNITS": "repo.code,repo.releases,repo.actions",
               "GITEA__packages__ENABLED": "false"}
        for key, value in env.items():
            cmd += ["-e", key + "=" + value]
        run(cmd + [GITEA_IMAGE])
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/api/v1/version", timeout=10) as response:
                json.load(response)
            break
        except (OSError, ValueError):
            print("Waiting for the new Gitea instance", flush=True)
            time.sleep(2)
    before = a.nginx_vhost.read_text()
    marker = "# fleet-public-gitea"
    if marker not in before and f"127.0.0.1:{a.port}" not in before:
        anchor = " location / { return 404; }"
        if before.count(anchor) != 1:
            raise RuntimeError("Expected one explicit nginx fallback; merge the documented location manually")
        if not a.nginx_backup.exists():
            a.nginx_backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_private(a.nginx_backup, before)
        location = f""" {marker}
 location = {prefix} {{ return 301 {prefix}/; }}
 location ~ ^{prefix}/ {{
  client_max_body_size 0;
  rewrite ^ $request_uri;
  rewrite ^{prefix}/(.*) /$1 break;
  proxy_pass http://127.0.0.1:{a.port}$uri;
  proxy_http_version 1.1;
  proxy_set_header Connection $http_connection;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_request_buffering off;
 }}
"""
        a.nginx_vhost.write_text(before.replace(anchor, location + anchor))
        try:
            run(["nginx", "-t"])
        except RuntimeError:
            a.nginx_vhost.write_text(before)
            raise
        run(["systemctl", "reload", "nginx"])
    cli = ["docker", "exec", "--user", "git", "fleet-gitea", "gitea", "admin", "user"]
    if cfg["username"] not in run(cli + ["list", "--config", "/data/gitea/conf/app.ini"]):
        run(cli + ["create", "--config", "/data/gitea/conf/app.ini", "--username", cfg["username"],
                   "--password", cfg["password"], "--email", "admin@users.noreply.local", "--admin",
                   "--must-change-password=false"])
    if not cfg.get("token"):
        token = run(cli + ["generate-access-token", "--config", "/data/gitea/conf/app.ini",
                          "--username", cfg["username"], "--token-name", "fleet-bootstrap",
                          "--scopes", "all", "--raw"]).strip().splitlines()[-1]
        if len(token) < 30:
            raise RuntimeError("Unexpected token result; no value has been logged")
        cfg["token"] = token
        write_private(secret_file, json.dumps(cfg, indent=2))

    def api(route, data=None):
        req = urllib.request.Request(a.url.rstrip("/") + "/api/v1" + route,
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Authorization": "token " + cfg["token"],
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    try:
        api("/orgs/" + a.organization)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        api("/orgs", {"username": a.organization, "full_name": "Distributed Workers", "visibility": "public"})
    for repo in REPOS:
        try:
            api("/repos/" + a.organization + "/" + repo)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            api("/orgs/" + a.organization + "/repos", {"name": repo, "private": False,
                                                      "auto_init": False, "default_branch": "main"})
    reg = a.private_dir / "runner-registration.token"
    if not reg.exists():
        write_private(reg, api("/orgs/" + a.organization + "/actions/runners/registration-token", {})["token"])
    runner_config = a.private_dir / "runner.yaml"
    write_private(runner_config, f"""log:
  level: info
runner:
  file: /data/.runner
  capacity: 1
  labels:
    - fleet-ci:docker://{a.job_image}
container:
  docker_host: "-"
  valid_volumes: []
  privileged: false
cache:
  enabled: false
""")
    exists = subprocess.run(["docker", "container", "inspect", "fleet-gitea-runner"], capture_output=True).returncode == 0
    if not exists:
        run(["docker", "run", "-d", "--name", "fleet-gitea-runner", "--restart", "unless-stopped",
             "--privileged", "-v", "fleet-gitea-runner-data:/data", "-v", "fleet-gitea-runner-docker:/var/lib/docker",
             "-v", str(reg) + ":/run/secrets/runner-registration:ro", "-v", str(runner_config) + ":/config.yaml:ro",
             "-e", "GITEA_INSTANCE_URL=" + a.url, "-e", "GITEA_RUNNER_REGISTRATION_TOKEN_FILE=/run/secrets/runner-registration",
             "-e", "GITEA_RUNNER_NAME=fleet-public-ci", "-e", "GITEA_RUNNER_LABELS=fleet-ci:docker://" + a.job_image,
             "-e", "CONFIG_FILE=/config.yaml", RUNNER_IMAGE])
    print("Public mirror and dedicated organization runner configured. Credentials remain in " + str(secret_file))


if __name__ == "__main__":
    main()
