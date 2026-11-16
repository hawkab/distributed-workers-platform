# Distributed Workers platform

Deployment and composition of independent components:

- [gateway](https://gitflic.ru/project/distributed-workers/gateway): durable execution ledger and broker bridge.
- [worker-android](https://gitflic.ru/project/distributed-workers/worker-android): Android executor and signed self-updates.
- [worker-portable](https://gitflic.ru/project/distributed-workers/worker-portable): Node.js for Linux/Windows, PHP cron adapter and signed self-updates.
- [protocol](https://gitflic.ru/project/distributed-workers/protocol): portable job and receipt formats.

Use separate databases, credentials and broker resources. Do not point this deployment
at unrelated agent queues. Production addresses and credentials belong in local
configuration outside Git.

`mirror-git.py` is an operator-local ignored script. It supports signed `commit`
and concurrent `push` to GitFlic, Gitea and GitHub; one failed mirror does not
stop the others. A nonzero final exit status reports incomplete replication.

## Local mirror commands

The local `mirror-git.py` is ignored by Git and installed in each checkout.

```sh
python3 mirror-git.py commit -m "Describe the change"
python3 mirror-git.py push
# From the workspace root, publish all component checkouts:
python3 mirror-git.py --all push
```

The local aliases `git mcommit` and `git mpush` invoke this script. Normal Git
commands retain their standard behavior; plain `git push` with several push URLs
can stop at the first failed transport. Use the mirror commands for publication.
The script attempts mirrors concurrently, preserves failed status under `.git/`,
and returns failure only after the remaining mirrors have been attempted.
Re-running `push` reconciles already successful mirrors without force-pushing.
Credentials are resolved by a local helper and never embedded in remote URLs.

The publisher sends the branch first and each new annotated tag as a separate
Git receive event, so release pipelines also work on forges that do not process
a combined first branch/tag push correctly.

## Native release triggering

GitHub and Gitea receive version tags as ordinary native workflow events.
The operator-local publisher additionally checks GitFlic for an existing pipeline
with the same project, tag and commit, then starts the native GitFlic pipeline
through its API when needed. This handles the hosted service's missing push
trigger without rebuilding artifacts outside GitFlic. A durable local receipt
prevents duplicate starts; uncertain responses are reconciled before retry.
The callback and all its credentials remain ignored and operator-local.
