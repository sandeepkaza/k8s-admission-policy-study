# Kubernetes Admission-Policy Engine Study

Corpus, implementations, benchmark harness, and raw data for the paper
*"Native CEL or Webhook? An Empirical Comparison of Kubernetes
Admission-Policy Engines"* (Venkata Sandeep Chowdary Kaza, 2026).

Three engines compared on a fixed 15-rule reference corpus:

| Engine | Version | Architecture |
|---|---|---|
| ValidatingAdmissionPolicy (VAP) | in-tree, K8s v1.34.0 | CEL evaluated inside kube-apiserver |
| OPA Gatekeeper | v3.20.1 | webhook + Rego (template/constraint) |
| Kyverno | v1.15.2 | webhook + YAML pattern DSL |

Headline results (benchmark runs 2026-07-14 and 2026-07-17; full detail in
[`results.md`](results.md)):

- **Expressiveness:** all 15 rules expressible in all three engines; 17/17
  correctness fixtures pass per engine.
- **Latency @15 policies** (median over 5×100 dry-run creates, vs. same-day
  baseline 5.3 ms): VAP 11.2 ms (+5.9), Kyverno 12.9 ms (+7.6),
  Gatekeeper 15.6 ms (+10.3). Gatekeeper pays its webhook round-trip even at
  zero constraints; Kyverno prunes to baseline; VAP grows near-linearly.
- **Drift detection** (pre-existing violating pod → first report): Kyverno
  ~12 s (background scan), Gatekeeper ~50 s (default 60 s audit interval),
  VAP: architecturally impossible (no audit/background mode).
- **Authoring cost** (median non-blank LOC/rule): Kyverno 17, Gatekeeper 25,
  VAP 26.

## Layout

```
corpus/corpus.yaml        15 requirements, each mapped to CIS K8s v1.9 / PSS / NIST 800-190
engines/vap.yaml          15 ValidatingAdmissionPolicy + binding pairs (CEL)
engines/gatekeeper.yaml   15 ConstraintTemplates (Rego)
engines/gatekeeper-constraints.yaml   15 Constraint instances
engines/kyverno.yaml      15 ClusterPolicies (pattern DSL)
fixtures/                 good.json, good_svc.json + 15 per-rule bad fixtures
gen_fixtures.py           fixture generator
bench.py                  verify (correctness matrix) + latency phases
scale_run.py              latency vs policy count (0/5/10/15), repeat runs
drift_run.py              drift-detection trials (kyverno | gatekeeper)
make_figures.py           paper figure from latency_scale.csv
*.csv                     raw samples and matrices (see below)
results.md                aggregated results, both runs
```

Raw data: `verify_<engine>.csv` (correctness), `latency_<engine>.csv` (run 1,
100 samples @15 policies), `latency_scale.csv` (run 2: engine, n_policies,
run, sample_ms), `drift_detection.csv` (engine, trial, detect_s).

## Reproducing

Testbed used: kind v0.30.0 (Kubernetes v1.34.0, single node) on Docker
Desktop 29.6.1 (WSL2), Windows 11 host. Python 3.11+ with the `kubernetes`
client package.

```sh
kind create cluster --name bench
kubectl create ns bench && kubectl label ns bench bench=true

# correctness + run-1 latency, engine at a time (install engine first; see below)
python bench.py --engine vap|gatekeeper|kyverno|baseline --phase both

# scale curves (applies/removes policy subsets itself)
python scale_run.py --engine vap --kubectl kubectl

# drift trials (webhook engines only)
python drift_run.py --engine kyverno --kubectl kubectl --trials 3
```

Engine install/uninstall is deliberately manual (each engine measured in
isolation on an otherwise idle cluster):

- Gatekeeper: `kubectl apply -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/v3.20.1/deploy/gatekeeper.yaml`,
  then `kubectl apply -f engines/gatekeeper.yaml` (templates).
- Kyverno: `kubectl apply -f https://github.com/kyverno/kyverno/releases/download/v1.15.2/install.yaml`.
  Note: uninstalling via `kubectl delete -f install.yaml` leaves Kyverno's
  dynamically created webhook configurations behind — delete them manually
  (`kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations`).
- VAP: nothing to install (in-tree); `scale_run.py` applies `engines/vap.yaml` subsets.

Absolute latencies are testbed-specific; orderings and same-day deltas are
the reproducible claims. See the paper's threats-to-validity section.

## License

MIT (see [LICENSE](LICENSE)). Rule sources (CIS Kubernetes Benchmark, Pod
Security Standards, NIST SP 800-190) are cited in `corpus/corpus.yaml`.
