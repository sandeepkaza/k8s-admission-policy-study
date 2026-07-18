# Paper 2 — Benchmark results, run 1 (2026-07-14)

## Testbed (record in Method)
- kind v0.30.0 cluster, single node, Kubernetes **v1.34.0**, Docker Desktop 29.6.1 (WSL2), Windows 11 host
- Engines: native ValidatingAdmissionPolicy (in-tree, K8s 1.34), OPA Gatekeeper **v3.20.1**, Kyverno **v1.15.2**
- Corpus: 15 requirements (corpus/corpus.yaml), each mapped to CIS K8s Benchmark v1.9 / PSS / NIST 800-190
- Engines measured in isolation (install → load 15 policies → measure → uninstall)
- Latency = client-observed server-side dry-run CREATE of the fully-compliant pod, 20 warmup + 100 samples

## Correctness / expressiveness (verify phase)
All 15 rules expressible and correctly enforced in all three engines: 17/17 fixtures
(15 bad denied + good pod + good service admitted) per engine. Fixture note: R01
(privileged) necessarily also violates R06 — API-level coupling, documented.

## Admission latency (ms, n=100 dry-run creates, 15 policies loaded)
| Engine | median | p95 | min | Δ median vs baseline |
|---|---|---|---|---|
| baseline (no engines) | 7.5 | 10.9 | 6.4 | — |
| ValidatingAdmissionPolicy (CEL, in-tree) | 12.8 | 18.7 | 11.2 | +5.3 |
| Kyverno 1.15.2 | 15.3 | 19.8 | 12.8 | +7.8 |
| Gatekeeper 3.20.1 | 17.2 | 20.9 | 15.4 | +9.7 |

Raw samples: latency_*.csv. Verify matrices: verify_*.csv.

## Authoring cost (non-blank/non-comment LOC per rule incl. binding/constraint objects)
| Engine | median LOC/rule | total (15 rules) |
|---|---|---|
| Kyverno | 17 | 267 |
| Gatekeeper (template+constraint) | 25 | 391 |
| VAP (policy+binding) | 26 | 391 |

## Observations for the paper (verify against data before drafting)
- Native VAP is the latency winner (in-process, no webhook round-trip) at zero install
  footprint — but has **no audit/background scan mode**: drift detection (RQ3) is
  impossible in-engine. Gatekeeper (audit controller) and Kyverno (background scans +
  PolicyReports) both do this. This trade-off is the paper's core finding candidate.
- Webhook engines add ~8–10ms median on this testbed; deltas will scale differently
  with policy count and object size — scale-curve runs needed (5/10/15/50 policies).
- Kyverno's pattern DSL is the tersest (17 LOC/rule) but two rules (R07, R14) forced
  escape hatches (foreach+deny, preconditions) — DSL cliff is a qualitative finding.
- Gatekeeper Rego v0 dialect bit us (R07 `in` keyword silently unavailable) — authoring
  footgun, worth a paragraph.

# Run 2 (2026-07-17) — scale curves, drift detection, repeat runs

Same testbed as run 1 (cluster `bench` kept running since; engines reinstalled/
removed per phase). Harness: scale_run.py (policy subsets R01..Rnn applied
incrementally, functional readiness = R01 bad fixture denied), drift_run.py.
Raw samples: latency_scale.csv, drift_detection.csv.

## Scale curve: admission latency (ms, median of 100 dry-run creates) vs policy count

| Engine | 0 policies | 5 | 10 | 15 |
|---|---|---|---|---|
| baseline (no engines, same day) | 5.2–5.4 (5 runs) | — | — | — |
| VAP | 6.5 | 7.6 | 9.5 | 11.0–11.9 (5 runs) |
| Kyverno | 5.8 | 10.7 | 12.9 | 12.6–13.9 (5 runs) |
| Gatekeeper | 8.7 | 11.5 | 13.6 | 15.2–16.0 (5 runs) |

- **Cross-day caveat:** today's baseline (5.2–5.4ms) is lower than run 1's (7.5ms)
  — absolute numbers shift with host load; compare deltas within a day, not across.
  Deltas vs same-day baseline @15 policies (pooled medians over 5×100 samples,
  baseline pooled 5.3): VAP 11.2 → +5.9, Kyverno 12.9 → +7.6, Gatekeeper 15.6 → +10.3
  — same ordering and similar magnitude as run 1.
- **Engine-installed-but-zero-policies floor differs:** Kyverno with 0 policies is at
  baseline (5.8ms — it prunes its resource-webhook rules when no policy matches),
  Gatekeeper with 0 constraints still pays the webhook round-trip (8.7ms — its
  ValidatingWebhookConfiguration intercepts regardless). VAP 0-policy ≈ baseline (in-tree).
- Curve shapes: VAP grows gently and near-linearly (~+1.5ms per 5 CEL policies);
  Kyverno jumps 0→5 (webhook engages once any policy matches pods) then flattens;
  Gatekeeper climbs steadily across all levels.

## Cross-run variance (5 × 100 samples at 15 policies, same session)

Medians spread ≤1.3ms per engine (VAP 11.0–11.9, Kyverno 12.6–13.9, GK 15.2–16.0);
baseline spread 0.2ms. p95 is noisy (one-off spikes to 30–78ms — Docker Desktop/WSL2
jitter); median is the stable statistic to report. Machine interactive but idle-ish;
not a controlled lab — stated as a threat to validity.

## Drift detection (RQ3): pre-existing violating pod, time from policy apply → first report

Method: policies deleted → privileged pod (r01_bad) actually created → corpus
re-applied (Kyverno with `background: true`) → poll (0.5s) until violation appears
(Kyverno: PolicyReport in bench ns; Gatekeeper: `status.violations` on r01 constraint).

| Engine | trial 1 | trial 2 | trial 3 | mechanism |
|---|---|---|---|---|
| Kyverno | 11.4s | 12.7s | 12.1s | background scan + reports-controller (event-driven) |
| Gatekeeper | 45.9s | 50.1s | 51.5s | audit controller, default 60s interval |
| VAP | N/A | N/A | N/A | no audit/background mode — drift invisible by design |

Confirms the core finding: VAP's latency win costs the entire drift-detection
capability; between webhook engines, Kyverno reports drift ~4× faster than
Gatekeeper's default audit cadence (tunable via --audit-interval; default compared).

## Cluster state after run 2
No engines installed (baseline state). Kyverno's dynamically-created webhook
configurations had to be deleted manually after `kubectl delete -f install.yaml`
— uninstall leftover worth a footnote (fails closed? no: failurePolicy Ignore,
but stale configs linger).

## Still to run / optional
- [ ] Latency vs object size (small vs large pod spec) — nice-to-have
- [ ] Optional scope extension (needs user's Azure sub): Azure Policy scan-latency section

## Cloud leg (EKS, 2026-07-18)

Real managed cluster: EKS `dr-eks` us-east-1, K8s 1.34.9, 4x t3.micro.
Same 15-rule corpus, fixtures, harness (`bench.py --kubecontext dr-eks`);
outputs `cloud-eks_*.csv`. Client on Windows over WAN -> absolute latencies
include internet RTT; the comparable quantity is the per-engine DELTA vs the
same-path baseline.

| engine | verify | median ms | delta vs baseline | p95 ms |
|---|---|---|---|---|
| baseline | 17/17 | 94.8 | - | 106.6 |
| VAP | 17/17 | 98.1 | +3.3 | 108.8 |
| Kyverno | 17/17 | 104.1 | +9.4 | 135.3 |
| Gatekeeper | 17/17 | 108.9 | +14.1 | 171.1 |

Findings: (1) correctness 17/17 for all engines replicates; (2) overhead
ordering VAP < Kyverno < Gatekeeper replicates on a managed control plane
(local deltas +5.9/+7.6/+10.3); (3) Gatekeeper's tail dominance replicates
(p95 171ms, ~1.6x its own median). (4) Deployability asymmetry: default
Gatekeeper footprint (3 replicas x 512Mi + audit 512Mi) is UNSCHEDULABLE on
1-GiB nodes - benchmarked at 1 replica / 200Mi request (config delta noted);
Kyverno (128Mi) and VAP (zero pods) deploy unchanged. Engine resource
footprint is a first-class selection criterion on constrained clusters.
