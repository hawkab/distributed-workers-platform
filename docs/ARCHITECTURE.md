# Shared component model

The six README diagrams are ownership views of one UML component model. Each
view has identical nodes and relationships. Only one component's border, fill
and explicit **THIS REPOSITORY** label change.

| Repository | Owned boundary | Shared dependency |
| --- | --- | --- |
| gateway | HTTPS API, admission, leases, canonical receipts, broker bridge, artifact/effect storage | protocol contracts; PostgreSQL, RabbitMQ, filesystem |
| worker-portable | Node/PHP execution adapters, resource admission, durable slot state, transfers and SDK updater | gateway API and protocol ABI |
| worker-android | Android service, Java/Rhino adapter, SQLite state, power admission and APK updater | gateway API and protocol ABI |
| worker-routeros | Minimal ARM64 image, supervisor, mounts and image packaging | signed PHP SDK from worker-portable |
| protocol | Wire schemas, portable ABI, examples, conformance and measurement clients | implemented by gateway and execution SDKs |
| platform | Deployment recipes, component composition and shared release tooling | independently versioned component repositories |

The application producer and result consumer are external. PostgreSQL is the
canonical execution ledger; RabbitMQ transports durable commands and small event
references. Binary content flows to filesystem artifact storage. A worker uses
outgoing HTTPS and its own credential; it does not connect to PostgreSQL or AMQP.

Claims are scoped by worker identity and slot. A repeated claim resumes that
slot's live attempt. Leases and monotonically increasing fences reject stale
canonical writes, while late output remains a candidate. Local checkpoints and
completion outboxes survive interruptions. Lower admission pauses new work; it
does not cancel an active computation.

Solid arrows represent runtime traffic, dashed arrows contracts or SDK reuse,
and dotted arrows deployment/update relationships. The contract and composition
links show principal entry points; protocol schemas also apply to all execution
adapters. These diagrams describe logical components, not machine counts or a
claim that every job can run on every backend. Capability matching selects an
adapter that implements the requested operation.

## Editing and rendering

The canonical model is [tools/render-architecture.py](../tools/render-architecture.py).
It emits editable DOT and self-contained, accessible SVG using Python's standard
library. Fixed positions keep the six ownership views comparable. No external
render service, downloaded JavaScript or production setting is involved.

From this repository:

```sh
python3 -B tools/render-architecture.py
# Workspace layout: WORKSPACE/repos/{platform,gateway,protocol,...}
python3 -B tools/render-architecture.py --workspace ../..
python3 -B -m unittest discover -s tests -v
```

Keep the generated DOT/SVG files in every repository so README rendering works
on GitFlic, Gitea and GitHub without Mermaid/PlantUML plugins. An installation
with Graphviz's full `neato` engine can also render the DOT's fixed routes with
`neato -n2 -Tsvg docs/architecture.dot -o docs/architecture.svg`.

Changes to the shared topology belong in the canonical model and must regenerate
all views. Repository-specific implementation details belong in that README's
boundary description. The tests compare every topology and check that each SVG
has exactly one owned component and no active or external content.
