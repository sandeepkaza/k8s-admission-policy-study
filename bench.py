"""Admission-engine benchmark harness (Paper 2, K8s scope).

Two phases against the current kubecontext (kind cluster), run per engine:

  verify  — every bad fixture must be DENIED, the good fixture ADMITTED.
            Output row per rule -> verify_<engine>.csv (correctness matrix).
  latency — client-observed CREATE latency of the good pod, server-side dry-run,
            WARMUP discarded + N measured samples -> latency_<engine>.csv (raw samples).

Usage:
  python bench.py --engine baseline|vap|gatekeeper|kyverno --phase verify|latency|both

Engine install/uninstall is orchestrated outside (RUNBOOK.md) so each engine is
measured in isolation on an otherwise idle cluster.
"""

import argparse
import csv
import json
import statistics
import time

from kubernetes import client, config
from kubernetes.client.rest import ApiException

NS = "bench"
WARMUP = 20
SAMPLES = 100
OUT_PREFIX = ""
RULES = [f"R{i:02d}" for i in range(1, 16)]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ensure_ns(core):
    try:
        core.create_namespace(client.V1Namespace(
            metadata=client.V1ObjectMeta(name=NS, labels={"bench": "true"})))
    except ApiException as e:
        if e.status != 409:
            raise


def try_create(core, obj, dry_run=None):
    """Returns (admitted: bool, latency_s: float, message: str)."""
    kwargs = {"dry_run": "All"} if dry_run else {}
    t0 = time.perf_counter()
    try:
        if obj["kind"] == "Pod":
            core.create_namespaced_pod(NS, obj, **kwargs)
        else:
            core.create_namespaced_service(NS, obj, **kwargs)
        return True, time.perf_counter() - t0, ""
    except ApiException as e:
        return False, time.perf_counter() - t0, (e.body or "")[:200]


def delete_quiet(core, obj):
    try:
        if obj["kind"] == "Pod":
            core.delete_namespaced_pod(obj["metadata"]["name"], NS, grace_period_seconds=0)
        else:
            core.delete_namespaced_service(obj["metadata"]["name"], NS)
    except ApiException:
        pass


def phase_verify(core, engine):
    rows = []
    good = load("fixtures/good.json")
    admitted, _, msg = try_create(core, good)
    rows.append({"engine": engine, "rule": "GOOD", "expected": "admit",
                 "actual": "admit" if admitted else "deny", "ok": admitted, "msg": msg})
    if admitted:
        delete_quiet(core, good)
    good_svc = load("fixtures/good_svc.json")
    admitted, _, msg = try_create(core, good_svc)
    rows.append({"engine": engine, "rule": "GOOD-SVC", "expected": "admit",
                 "actual": "admit" if admitted else "deny", "ok": admitted, "msg": msg})
    if admitted:
        delete_quiet(core, good_svc)

    for rid in RULES:
        fixture = load(f"fixtures/{rid.lower()}_bad.json")
        admitted, _, msg = try_create(core, fixture)
        expected_deny = engine != "baseline"
        actual = "admit" if admitted else "deny"
        ok = (actual == "deny") if expected_deny else (actual == "admit")
        rows.append({"engine": engine, "rule": rid,
                     "expected": "deny" if expected_deny else "admit",
                     "actual": actual, "ok": ok, "msg": msg})
        if admitted:
            delete_quiet(core, fixture)

    out = f"{OUT_PREFIX}verify_{engine}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["engine", "rule", "expected", "actual", "ok", "msg"])
        w.writeheader()
        w.writerows(rows)
    fails = [r for r in rows if not r["ok"]]
    print(f"{out}: {len(rows) - len(fails)}/{len(rows)} as expected")
    for r in fails:
        print(f"  UNEXPECTED {r['rule']}: {r['actual']} — {r['msg'][:80]}")


def phase_latency(core, engine):
    good = load("fixtures/good.json")
    good["metadata"]["name"] = "latency-probe"
    for _ in range(WARMUP):
        try_create(core, good, dry_run=True)
    samples = []
    for _ in range(SAMPLES):
        admitted, dt, msg = try_create(core, good, dry_run=True)
        if not admitted:
            raise SystemExit(f"latency probe denied under {engine}: {msg}")
        samples.append(dt * 1000)
    out = f"{OUT_PREFIX}latency_{engine}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["engine", "sample_ms"])
        for s in samples:
            w.writerow([engine, f"{s:.3f}"])
    qs = statistics.quantiles(samples, n=20)
    print(f"{out}: median={statistics.median(samples):.1f}ms p95={qs[18]:.1f}ms "
          f"min={min(samples):.1f} max={max(samples):.1f} n={SAMPLES}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True,
                    choices=["baseline", "vap", "gatekeeper", "kyverno"])
    ap.add_argument("--phase", default="both", choices=["verify", "latency", "both"])
    ap.add_argument("--kubecontext", default=None,
                    help="kubeconfig context (default: current)")
    ap.add_argument("--out-prefix", default="",
                    help="prefix for output CSVs, e.g. cloud-eks_")
    args = ap.parse_args()
    global OUT_PREFIX
    OUT_PREFIX = args.out_prefix

    config.load_kube_config(context=args.kubecontext)
    core = client.CoreV1Api()
    ensure_ns(core)

    if args.phase in ("verify", "both"):
        phase_verify(core, args.engine)
    if args.phase in ("latency", "both"):
        phase_latency(core, args.engine)


if __name__ == "__main__":
    main()
