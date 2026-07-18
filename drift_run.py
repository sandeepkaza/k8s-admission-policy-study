"""Drift-detection harness (Paper 2, K8s scope). RQ3.

Scenario: a violating resource already exists in the cluster (created while no
policy objects were loaded — i.e. pre-existing drift). The 15-rule corpus is
then (re)applied and we measure the time until the engine's out-of-band
mechanism first reports the violation:

  kyverno    — background scan -> PolicyReport in the bench namespace
  gatekeeper — audit controller -> status.totalViolations on the R01 constraint

VAP has no audit/background mode: N/A by design (paper finding).

The drift object is fixtures/r01_bad.json (privileged pod), really created
(not dry-run). For kyverno the policies are applied with background: true
(the corpus file ships background: false, admission-only).

Usage:
  python drift_run.py --engine kyverno|gatekeeper --kubectl <path> [--trials 3]

Output: appends to drift_detection.csv (engine, trial, detect_s).
"""

import argparse
import csv
import json
import os
import subprocess
import time

from kubernetes import client, config

import bench

OUT = "drift_detection.csv"
ENGINE_YAML = {"vap": "engines/vap.yaml", "kyverno": "engines/kyverno.yaml",
               "gatekeeper": "engines/gatekeeper-constraints.yaml"}
POLL_S = 0.5
TIMEOUT_S = 600


def kubectl(kubectl_path, args, stdin_text=None, check=True):
    r = subprocess.run([kubectl_path] + args, input=stdin_text,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"kubectl {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout


def load_policies_text(engine):
    with open(ENGINE_YAML[engine], encoding="utf-8") as f:
        text = f.read()
    if engine == "kyverno":
        text = text.replace("background: false", "background: true")
    return text


def detected_kyverno(kubectl_path, pod_name):
    out = kubectl(kubectl_path, ["get", "polr", "-n", bench.NS, "-o", "json"],
                  check=False)
    if not out:
        return False
    for item in json.loads(out).get("items", []):
        owner = item.get("scope") or {}
        if owner.get("name") != pod_name:
            continue
        for res in item.get("results", []):
            if res.get("result") == "fail" and "r01" in res.get("policy", ""):
                return True
    return False


def detected_gatekeeper(kubectl_path, pod_name):
    out = kubectl(kubectl_path,
                  ["get", "constraints", "-o", "json"], check=False)
    if not out:
        return False
    for item in json.loads(out).get("items", []):
        if "r01" not in item["metadata"]["name"]:
            continue
        for v in (item.get("status") or {}).get("violations", []) or []:
            if v.get("name") == pod_name:
                return True
    return False


def one_trial(core, args, trial):
    yaml_path = ENGINE_YAML[args.engine]
    kubectl(args.kubectl, ["delete", "-f", yaml_path,
                           "--ignore-not-found", "--wait=true"])
    time.sleep(10)  # let webhooks drop the deleted policies from cache

    bad = bench.load("fixtures/r01_bad.json")
    bad["metadata"]["name"] = f"drift-victim-{trial}"
    admitted, _, msg = bench.try_create(core, bad)
    if not admitted:
        raise SystemExit(f"drift pod still denied after policy delete: {msg}")

    t0 = time.perf_counter()
    kubectl(args.kubectl, ["apply", "-f", "-"],
            load_policies_text(args.engine))
    detect = detected_kyverno if args.engine == "kyverno" else detected_gatekeeper
    while time.perf_counter() - t0 < TIMEOUT_S:
        if detect(args.kubectl, bad["metadata"]["name"]):
            dt = time.perf_counter() - t0
            bench.delete_quiet(core, bad)
            return dt
        time.sleep(POLL_S)
    bench.delete_quiet(core, bad)
    raise SystemExit(f"no detection within {TIMEOUT_S}s (trial {trial})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["kyverno", "gatekeeper"])
    ap.add_argument("--kubectl", required=True)
    ap.add_argument("--trials", type=int, default=3)
    args = ap.parse_args()

    config.load_kube_config()
    core = client.CoreV1Api()
    bench.ensure_ns(core)

    new = not os.path.exists(OUT)
    for trial in range(1, args.trials + 1):
        dt = one_trial(core, args, trial)
        print(f"{args.engine} trial {trial}: detected in {dt:.1f}s", flush=True)
        with open(OUT, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["engine", "trial", "detect_s"])
                new = False
            w.writerow([args.engine, trial, f"{dt:.1f}"])


if __name__ == "__main__":
    main()
