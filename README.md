# Kubernetes Admission-Policy Engine Study

Corpus, implementations, benchmark harness, and raw data for the paper
*"Native CEL or Webhook? An Empirical Comparison of Kubernetes
Admission-Policy Engines"* (Venkata Sandeep Chowdary Kaza, 2026).

**Benchmark your own cluster's admission engines in ~10 minutes** — or
reproduce the paper's full local + managed-cloud (EKS) results.

Three engines, one fixed 15-rule corpus:

| Engine | Version | Architecture |
|---|---|---|
| ValidatingAdmissionPolicy (VAP) | in-tree, K8s v1.34.0 | CEL evaluated inside kube-apiserver |
| OPA Gatekeeper | v3.20.1 | webhook + Rego (template/constraint) |
| Kyverno | v1.15.2 | webhook + YAML pattern DSL |

## Headline results

- **Expressiveness/correctness:** all 15 rules expressible in all three
  engines; 17/17 fixtures pass per engine — locally **and** on EKS.
- **Latency @15 policies** (median deltas vs same-environment baseline):
  local kind — VAP +5.9 ms, Kyverno +7.6, Gatekeeper +10.3;
  managed EKS — VAP **+3.3**, Kyverno **+9.4**, Gatekeeper **+14.1**.
  Same ordering everywhere. Gatekeeper pays its webhook round-trip even at
  zero constraints; Kyverno prunes to baseline when idle; VAP grows
  near-linearly.
- **Drift detection** (pre-existing violation → first report): Kyverno ~12 s,
  Gatekeeper ~50 s (default 60 s audit), VAP: architecturally impossible.
- **Authoring cost** (median LOC/rule): Kyverno 17, Gatekeeper 25, VAP 26.
- **Deployability (cloud finding):** Gatekeeper's default deployment
  (3×512 MiB + 512 MiB audit) is unschedulable on 1-GiB nodes; Kyverno
  (128 MiB) and VAP (no pods) deploy unchanged.

Full numbers: [`results.md`](results.md). Every table in the paper traces to
a CSV in this repo.

## What's in this repo

```
corpus/corpus.yaml            15 requirements, each mapped to CIS K8s v1.9 / PSS / NIST 800-190
engines/vap.yaml              the corpus as 15 ValidatingAdmissionPolicy + binding pairs (CEL)
engines/gatekeeper.yaml       the corpus as 15 ConstraintTemplates (Rego)
engines/gatekeeper-constraints.yaml   15 Constraint instances
engines/kyverno.yaml          the corpus as 15 ClusterPolicies (pattern DSL)
fixtures/                     good.json, good_svc.json + 15 per-rule bad fixtures
gen_fixtures.py               fixture generator
bench.py                      verify (correctness) + latency phases; --kubecontext/--out-prefix for any cluster
scale_run.py                  latency vs policy count (0/5/10/15), repeat runs
drift_run.py                  drift-detection trials (webhook engines)
bench-eks.ps1 / bench-eks3.ps1  cloud-leg runners (engine install -> bench -> full uninstall)
make_figures.py               regenerates the paper's figures from the CSVs
verify_*.csv latency_*.csv latency_scale.csv drift_detection.csv   local raw data
cloud-eks_*.csv               EKS raw data
```

## Reproducing — step by step

### 0. Prerequisites (5 min)

- Docker + [kind](https://kind.sigs.k8s.io/) v0.30+ (local leg), or any
  K8s ≥1.30 cluster you can reach with `kubectl` (VAP needs ≥1.30 GA)
- `kubectl` on PATH
- Python 3.11+ with the Kubernetes client: `pip install kubernetes`

### 1. Create the test cluster (2 min)

```sh
kind create cluster --name bench
kubectl create ns bench
kubectl label ns bench bench=true      # policies are scoped to this label
```

Checkpoint: `kubectl get ns bench --show-labels` shows `bench=true`.

### 2. Baseline (no engines) — 3 min

```sh
python bench.py --engine baseline --phase both
```

Expected output: `verify_baseline.csv: 17/17 as expected` (bad fixtures are
*admitted* — nothing enforces yet) and a latency line like
`latency_baseline.csv: median=5.3ms ...`. Your absolute numbers will differ;
orderings and same-session deltas are the reproducible claims.

### 3. VAP (nothing to install) — 5 min

```sh
kubectl apply -f engines/vap.yaml
sleep 15                                # let policies compile
python bench.py --engine vap --phase both
kubectl delete -f engines/vap.yaml
```

Checkpoint: `verify_vap.csv: 17/17 as expected` — now the 15 bad fixtures are
*denied* and the 2 good fixtures admitted.

### 4. Gatekeeper — 10 min

```sh
kubectl apply -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/v3.20.1/deploy/gatekeeper.yaml
kubectl -n gatekeeper-system rollout status deploy/gatekeeper-controller-manager --timeout=300s
kubectl apply -f engines/gatekeeper.yaml            # ConstraintTemplates
sleep 20                                            # template CRDs register
kubectl apply -f engines/gatekeeper-constraints.yaml
sleep 30                                            # constraints sync
python bench.py --engine gatekeeper --phase both
# full uninstall (reverse order):
kubectl delete -f engines/gatekeeper-constraints.yaml
kubectl delete -f engines/gatekeeper.yaml
kubectl delete -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/v3.20.1/deploy/gatekeeper.yaml
```

Small-node note: on nodes with ≤1 GiB memory the default deployment will sit
`Pending` (the paper's deployability finding). Scale to 1 replica and lower
the memory request before the rollout wait:
`kubectl -n gatekeeper-system scale deploy gatekeeper-controller-manager --replicas=1`
plus a memory-request patch to ~200Mi.

### 5. Kyverno — 10 min

```sh
kubectl apply --server-side -f https://github.com/kyverno/kyverno/releases/download/v1.15.2/install.yaml
kubectl -n kyverno rollout status deploy/kyverno-admission-controller --timeout=300s
kubectl apply -f engines/kyverno.yaml
sleep 20
python bench.py --engine kyverno --phase both
kubectl delete -f engines/kyverno.yaml
kubectl delete -f https://github.com/kyverno/kyverno/releases/download/v1.15.2/install.yaml
```

**Gotcha (reported in the paper):** Kyverno's uninstall leaves its
dynamically created webhook configurations behind. Delete them or the next
engine's numbers are contaminated:

```sh
kubectl delete validatingwebhookconfigurations -l webhook.kyverno.io/managed-by=kyverno
kubectl delete mutatingwebhookconfigurations -l webhook.kyverno.io/managed-by=kyverno
```

### 6. Scale curves and drift (optional, ~40 min)

```sh
python scale_run.py --engine vap --kubectl kubectl        # 0/5/10/15 policies
python drift_run.py --engine kyverno --kubectl kubectl --trials 3
python drift_run.py --engine gatekeeper --kubectl kubectl --trials 3
```

`scale_run.py` applies/removes policy subsets itself (engine must be
installed for webhook engines). `drift_run.py` creates a real violating pod
*before* applying policies, then polls until the engine first reports it.

### 7. Your own cluster / cloud leg

Everything above works against any cluster — point the harness at a context
and prefix the outputs so nothing is overwritten:

```sh
python bench.py --engine vap --phase both --kubecontext my-prod-cluster --out-prefix mycluster_
```

`bench-eks.ps1` / `bench-eks3.ps1` are the exact runners used for the paper's
EKS leg (engine install → bench → verified-clean uninstall, all four engines
in sequence).

### 8. Regenerate the paper's figures

```sh
pip install matplotlib
python make_figures.py     # fig_scale.pdf, fig_drift.pdf, fig_cloud_delta.pdf from the committed CSVs
```

## Citing

Use GitHub's **"Cite this repository"** button (backed by
[`CITATION.cff`](CITATION.cff)). License: MIT. Rule sources (CIS Kubernetes
Benchmark, Pod Security Standards, NIST SP 800-190) are cited per rule in
`corpus/corpus.yaml`.
