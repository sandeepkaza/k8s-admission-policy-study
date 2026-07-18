"""Scale-curve + repeat-run harness (Paper 2, K8s scope).

Measures admission latency as a function of loaded-policy count, per engine:

  levels 0/5/10/15 policies (incremental R01..Rnn), 1 run of 100 samples each,
  plus --runs-at-max repeat runs at the top level for cross-run variance.

Reuses bench.py's client + sampling primitives. Engine install/uninstall is
still orchestrated outside; this script only manages the policy objects
(kubectl delete/apply of per-rule doc groups split from engines/<file>.yaml).

Usage:
  python scale_run.py --engine kyverno --kubectl <path-to-kubectl>
  python scale_run.py --engine baseline --kubectl <path>   # 0-level only, 5 runs

Output: appends to latency_scale.csv (engine, n_policies, run, sample_ms).
"""

import argparse
import csv
import os
import re
import statistics
import subprocess
import time

from kubernetes import client, config

import bench

ENGINE_YAML = {
    "vap": "engines/vap.yaml",
    "kyverno": "engines/kyverno.yaml",
    "gatekeeper": "engines/gatekeeper-constraints.yaml",
}
LEVELS = [0, 5, 10, 15]
OUT = "latency_scale.csv"


def split_rules(path):
    """Return {\"R01\": [docstr, ...], ...} — every doc grouped by rule id."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    groups = {}
    for doc in re.split(r"(?m)^---\s*$", raw):
        if not doc.strip():
            continue
        m = re.search(r"name:\s*\{?\s*(r\d{2})", doc)
        if not m:
            raise SystemExit(f"doc without rule-id name in {path}:\n{doc[:200]}")
        groups.setdefault(m.group(1).upper(), []).append(doc)
    return groups


def kubectl(kubectl_path, args, stdin_text=None):
    r = subprocess.run([kubectl_path] + args, input=stdin_text,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"kubectl {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout


def apply_docs(kubectl_path, docs):
    kubectl(kubectl_path, ["apply", "-f", "-"], "\n---\n".join(docs))


def delete_all(kubectl_path, yaml_path):
    subprocess.run([kubectl_path, "delete", "-f", yaml_path,
                    "--ignore-not-found", "--wait=true"],
                   capture_output=True, text=True)


def wait_enforcing(core, timeout=120):
    """Functional readiness: poll until R01's bad fixture is denied (dry-run)."""
    bad = bench.load("fixtures/r01_bad.json")
    deadline = time.time() + timeout
    while time.time() < deadline:
        admitted, _, _ = bench.try_create(core, bad, dry_run=True)
        if not admitted:
            return
        time.sleep(2)
    raise SystemExit("policies applied but R01 still not enforcing after "
                     f"{timeout}s")


def sample_latency(core, n=bench.SAMPLES, warmup=bench.WARMUP):
    good = bench.load("fixtures/good.json")
    good["metadata"]["name"] = "latency-probe"
    for _ in range(warmup):
        bench.try_create(core, good, dry_run=True)
    samples = []
    for _ in range(n):
        admitted, dt, msg = bench.try_create(core, good, dry_run=True)
        if not admitted:
            raise SystemExit(f"latency probe denied: {msg}")
        samples.append(dt * 1000)
    return samples


def append_rows(engine, n_policies, run, samples):
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["engine", "n_policies", "run", "sample_ms"])
        for s in samples:
            w.writerow([engine, n_policies, run, f"{s:.3f}"])


def report(engine, n_policies, run, samples):
    qs = statistics.quantiles(samples, n=20)
    print(f"{engine} n={n_policies} run={run}: "
          f"median={statistics.median(samples):.1f}ms p95={qs[18]:.1f}ms "
          f"min={min(samples):.1f} max={max(samples):.1f}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True,
                    choices=["baseline", "vap", "gatekeeper", "kyverno"])
    ap.add_argument("--kubectl", required=True)
    ap.add_argument("--runs-at-max", type=int, default=5)
    args = ap.parse_args()

    config.load_kube_config()
    core = client.CoreV1Api()
    bench.ensure_ns(core)

    if args.engine == "baseline":
        for run in range(1, args.runs_at_max + 1):
            samples = sample_latency(core)
            append_rows("baseline", 0, run, samples)
            report("baseline", 0, run, samples)
        return

    yaml_path = ENGINE_YAML[args.engine]
    groups = split_rules(yaml_path)
    rules = sorted(groups)
    delete_all(args.kubectl, yaml_path)
    time.sleep(5)

    applied = 0
    for level in LEVELS:
        if level > 0:
            docs = [d for rid in rules[applied:level] for d in groups[rid]]
            apply_docs(args.kubectl, docs)
            applied = level
            wait_enforcing(core)
            time.sleep(3)
        runs = args.runs_at_max if level == LEVELS[-1] else 1
        for run in range(1, runs + 1):
            samples = sample_latency(core)
            append_rows(args.engine, level, run, samples)
            report(args.engine, level, run, samples)


if __name__ == "__main__":
    main()
