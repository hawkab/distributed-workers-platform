# Isolated public Gitea release mirror

Run `deploy-public-gitea.py` as root on the Docker/nginx host. The script creates only
`fleet-gitea` and `fleet-gitea-runner`, three separate named data volumes and a
single nginx subpath. It does not connect to an existing Git service, database,
broker, VPN or SSH tunnel.

```sh
python3 deploy-public-gitea.py \
  --url https://example.invalid/git/ \
  --nginx-vhost /etc/nginx/sites-enabled/public-vhost.conf \
  --nginx-backup /root/.local/gitea-nginx-before.conf
```

The vhost must already have working public HTTPS and exactly one explicit
` location / { return 404; }` fallback, used as the merge anchor. The existing
vhost is preserved in the single chosen backup file. nginx is validated before
reload; a failed validation restores the immediate prior contents. Preserve the
new location in any external vhost generator.

The deployment uses official stable Gitea 28.4.0 and Gitea Runner 5.2.0 images
pinned by digest. SQLite lives in `fleet-gitea-data`, separate from application
queues and databases. Public registration and SSH are disabled. Git operations
use HTTPS. Four initially empty public repositories are created under the chosen
organization: `gateway`, `worker-android`, `protocol`, `platform`.

Administrative password/token are generated on the target and stored only in
`/etc/fleet-worker-gitea/bootstrap.json` (directory 700, file 600). Read them through
an existing private administrative connection; do not print or put them in CI.
The registration token file and runner volume are also secrets.

The organization runner has label `fleet-ci`, a separate Docker-in-Docker daemon
and no host Docker socket. Its job containers are not privileged and cannot
request arbitrary bind mounts. This is isolation from ordinary job mounts,
not a claim that privileged DinD is a VM security boundary. Only owner-controlled
pushes/tags run CI. Do not add pull-request triggers to publishing workflows or
make the runner available to untrusted repositories. No APK, release or GPG
private key is stored on this mirror.

For Android release verification, the default job image must be extended with a
full JDK21 and Android SDK build-tools36.0.0 (`apksigner`, `aapt`), in addition to
Python3/OpenSSL/git/node. Copy only those nonsecret vendor tools into a new image;
never copy a home directory or signing directory. Set `JAVA_HOME=/opt/java21`,
`ANDROID_HOME=/opt/android-sdk` and add both tool directories to PATH. Use
`--job-image fleet-gitea-job:1` after building that image. For a local-only image,
load it into the runner's separate Docker daemon before CI:

```sh
docker save fleet-gitea-job:1 | docker exec -i fleet-gitea-runner docker load
```

The runner must be idle before replacing its container to change labels/images;
preserve both runner volumes and do not force-stop a live job. Existing-container
configuration is intentionally not silently rewritten by a rerun of this script.

Verification from a machine outside the server:

```sh
curl --fail https://example.invalid/git/api/v1/version
curl --fail https://example.invalid/git/api/v1/orgs/distributed-workers/repos
```

Check that API `clone_url`, web links and release `browser_download_url` all use
public HTTPS with `/git/`. The nginx rewrite follows the official subpath example
and preserves encoded slashes. Container registry support is disabled, so no
additional `/v2` route is exposed. Finally push a signed owner-controlled version
tag, wait for an actual native Actions run, and verify its anonymous release
artifacts; an online runner alone is not evidence of a successful pipeline.

Sources: [Docker installation](https://docs.gitea.com/installation/install-with-docker/),
[subpath proxy](https://docs.gitea.com/administration/reverse-proxies/),
[runner Docker isolation](https://docs.gitea.com/runner/installation/docker/),
[job token permissions](https://docs.gitea.com/usage/actions/token-permissions/).

## Private deployment settings

Copy `deployment.example.json` from the repository root to the ignored
`deployment.local.json`, then edit its `public_host` locally. Validate without
changing services with:

```sh
python3 deploy/configure-host.py --config deployment.local.json --check
```

Run the same command without `--check` as root only on the intended host.
Keep real hostnames, addresses and private configuration outside Git.

## Gateway artifact storage and streaming

The gateway uses `WORKER_ARTIFACT_DIR` for durable binary chunks and complete
content-addressed objects. The provisioning default is the private `artifacts`
subdirectory of `/var/lib/fleet-worker-gateway`; an optional `artifact_dir` in
ignored deployment settings can select a dedicated persistent filesystem.
That filesystem must support hard links, file/directory fsync and the service
user's writes. Do not expose it as a web document root. Preserve the directory
together with fleet PostgreSQL metadata when moving or restoring the service.

The unit declares `StateDirectory`, an explicit writable path under
`ProtectSystem=strict`, and `TimeoutStopSec=infinity`. The Go server drains active
HTTP requests on SIGTERM rather than cutting an active upload off at a fixed
deadline. Quiesce new work and check active workers before maintenance; a forced
stop remains an explicit operator action.

Only binary chunk URLs bypass `client_max_body_size`; JSON metadata still has
the gateway's 16 MiB control budget. Upload proxying uses HTTP/1.1 with request
buffering disabled, including chunked requests. Both device-scoped and admin
artifact downloads disable response buffering and gzip, preserving exact bytes.
Read/send timeouts apply to inactivity between I/O operations, not total transfer
duration. Authentication and job/attempt ownership remain enforced by the gateway.

`configure-host.py` provisions a complete dedicated host configuration. For an
existing deployment, apply reviewed environment, unit and binary-location changes
without rerunning the whole provisioner or replacing unrelated live locations.
Preserve the current public Git subpath and other deliberate host differences.
Validate nginx before reload, ensure the artifact path is writable as the service
user, then check a chunked upload above 16 MiB and a checksum-verified download.

Worker resource profiles use the authenticated `X-Worker-Profile` header. The
proxy permits a large header up to the Go HTTP server's existing 1 MiB default
capacity, rather than nginx's smaller per-header default. Small normal requests
use the regular header buffer. The gateway validates the profile and binds it
to the credential; a caller cannot select another worker by an ID in a header.
