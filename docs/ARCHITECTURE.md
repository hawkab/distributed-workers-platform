# Two architecture views

The README separates runtime communication from source/package dependencies.
Each view has one shared topology, reproduced in all six repositories with a
repository-specific ownership highlight. `architecture.*` describes execution;
`repositories.*` describes UML package dependencies.

## Runtime: who calls whom

The primary path is application → gateway API ← worker. Both callers initiate
HTTPS requests. A claim response carries the assigned job back to the worker;
the gateway does not open an inbound connection to a device.

1. The application submits a task with an idempotency key and requirements.
2. The worker claims with its capabilities, resource profile and slot ID. The
   gateway selects/locks a job in PostgreSQL and records a fenced attempt.
3. The worker renews its lease, executes the task, streams binary chunks and
   submits a completion. Artifact offsets and result receipts are acknowledged
   only after their durable writes.
4. The application reads the canonical result and any referenced artifact.

PostgreSQL is the execution ledger and claim scheduler. The artifact filesystem
holds binary chunks and sealed objects; binary bodies are not RabbitMQ messages.
RabbitMQ is an optional integration bridge for incoming commands and outgoing
lifecycle/result references, using the gateway's transactional inbox/outbox.
**Workers do not consume broker queues or connect to PostgreSQL.**

The worker frame contains adapter types, not an inventory of devices. Node and
PHP are alternative engines in worker-portable; Android has its own service and
engine. The RouterOS frame contains a local PHP SDK instance: a build/runtime
reuse relationship, not an RPC from a router to a remote PHP host. Every slot
retains local checkpoints and a completion outbox, separate from server storage.

Blue runtime boxes identify code supplied by the current repository. The
portable repository supplies several engines/instances, so several boxes may be
blue. Protocol/platform have no running service to highlight; their scope is
stated in the caption and their single package is highlighted in the second view.

## Source: who owns and reuses what

| Repository | Owns | Contract / reuse |
| --- | --- | --- |
| gateway | HTTPS API, admission, fenced leases, canonical receipts, artifact/effect storage, AMQP bridge | Conforms to protocol |
| worker-portable | Node/PHP engines, resource admission, durable slot state, transfers, SDK updater | Conforms to protocol |
| worker-android | Android foreground service, Java/Rhino engine, SQLite state, power admission, APK updater | Conforms to protocol |
| worker-routeros | ARM64 image, supervisor, mount contract, image packaging | Packages signed portable PHP SDK |
| protocol | Wire schemas, portable JS ABI, examples and conformance/measurement clients | Contract, not a daemon |
| platform | Deployment recipes, component manifests and shared release tooling | Composes versioned component releases |

Dashed UML dependencies point from client to supplier. The platform's manifest
also pins a protocol release; it is a bundle snapshot, not live device inventory.
The package diagram shows the principal architecture dependencies rather than
every vendored CI helper or configuration field. Component repositories keep
their own build/release pipelines; platform is not a central build daemon.

## Updates are separate from task execution

Signed update sources are **alternatives tried in order**: Gitea, GitFlic, GitHub.
There is no provider-to-provider task or update connection. The SDK/APK updater
checks signatures and version floors, and installs at a safe point after active
slots/outboxes have drained. Android also validates the APK signing certificate.

RouterOS image replacement is an operator-controlled deployment operation. The
PHP SDK inside that image can update independently through its signed runtime
chain. A signed image in a release does not imply automatic container replacement.

## Regeneration and verification

The canonical model is [tools/render-architecture.py](../tools/render-architecture.py).
It defines named components and typed links once, and emits two SVG/DOT views
per repository. Routes are orthogonal and captions use distinct semantics for
calls, optional broker messages and package dependencies. SVG generation uses
Python's standard library. Local Chromium and Pillow render PNG at native scale;
PNG contains its vector source hash to detect stale previews. No diagram server
or production configuration is required.

```sh
python3 -B tools/render-architecture.py --png
# Workspace contains repos/{platform,gateway,protocol,...}
python3 -B tools/render-architecture.py --workspace ../.. --png
python3 -B -m unittest discover -s tests -v
```

PNG is embedded in README because GitFlic serves raw SVG as text. SVG/DOT remain
linked for editing and scaling. Tests check both topology families, call and
reuse directions, valid box/route geometry, SVG safety, ownership and preview
source hashes. Edit the common model and regenerate every view together.
