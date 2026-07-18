"""Generate per-rule pass/fail pod fixtures (fixtures/rXX_bad.json + baseline good pod).

The baseline pod complies with ALL 15 corpus rules. Each bad fixture mutates exactly
one aspect so it violates exactly its rule. Written as JSON (kubectl and the python
client both accept it) — machine-diffable for the paper's artifact.
"""

import copy
import json
import os

GOOD = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {
        "name": "good",
        "labels": {"app.kubernetes.io/name": "bench"},
    },
    "spec": {
        "automountServiceAccountToken": False,
        "securityContext": {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [{
            "name": "app",
            "image": "docker.io/library/nginx:1.27",
            "resources": {"limits": {"cpu": "100m", "memory": "128Mi"}},
            "securityContext": {
                "privileged": False,
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "runAsNonRoot": True,
                "capabilities": {"drop": ["ALL"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            },
        }],
    },
}


def bad(rule_id, mutate):
    p = copy.deepcopy(GOOD)
    p["metadata"]["name"] = f"bad-{rule_id.lower()}"
    mutate(p)
    return p


MUTATIONS = {
    # privileged=true forbids allowPrivilegeEscalation=false at API level, so this
    # fixture necessarily also violates R06 — attribution noted in the paper.
    "R01": lambda p: p["spec"]["containers"][0]["securityContext"].update(
        privileged=True, allowPrivilegeEscalation=True),
    "R02": lambda p: p["spec"].update(hostNetwork=True),
    "R03": lambda p: p["spec"].update(hostPID=True),
    "R04": lambda p: p["spec"].update(volumes=[{"name": "h", "hostPath": {"path": "/etc"}}]),
    "R05": lambda p: (p["spec"]["securityContext"].pop("runAsNonRoot"),
                      p["spec"]["containers"][0]["securityContext"].pop("runAsNonRoot")),
    "R06": lambda p: p["spec"]["containers"][0]["securityContext"].update(allowPrivilegeEscalation=True),
    "R07": lambda p: p["spec"]["containers"][0]["securityContext"].update(capabilities={"drop": ["NET_RAW"]}),
    "R08": lambda p: p["spec"]["containers"][0].update(image="docker.io/library/nginx:latest"),
    "R09": lambda p: p["spec"]["containers"][0].update(resources={}),
    "R10": lambda p: p["spec"]["containers"][0].update(image="ghcr.io/evil/nginx:1.27"),
    "R11": lambda p: p["metadata"].update(labels={}),
    # R12 is a Service rule — separate fixture below
    "R13": lambda p: p["spec"]["containers"][0]["securityContext"].update(readOnlyRootFilesystem=False),
    "R14": lambda p: p["spec"].pop("automountServiceAccountToken"),
    "R15": lambda p: (p["spec"]["securityContext"].pop("seccompProfile"),
                      p["spec"]["containers"][0]["securityContext"].pop("seccompProfile")),
}

SVC_GOOD = {
    "apiVersion": "v1", "kind": "Service",
    "metadata": {"name": "good-svc", "labels": {"app.kubernetes.io/name": "bench"}},
    "spec": {"type": "ClusterIP", "selector": {"app.kubernetes.io/name": "bench"},
             "ports": [{"port": 80}]},
}
SVC_BAD = {
    "apiVersion": "v1", "kind": "Service",
    "metadata": {"name": "bad-r12", "labels": {"app.kubernetes.io/name": "bench"}},
    "spec": {"type": "NodePort", "selector": {"app.kubernetes.io/name": "bench"},
             "ports": [{"port": 80}]},
}

os.makedirs("fixtures", exist_ok=True)
with open("fixtures/good.json", "w", encoding="utf-8") as f:
    json.dump(GOOD, f, indent=1)
for rid, mut in MUTATIONS.items():
    with open(f"fixtures/{rid.lower()}_bad.json", "w", encoding="utf-8") as f:
        json.dump(bad(rid, mut), f, indent=1)
with open("fixtures/good_svc.json", "w", encoding="utf-8") as f:
    json.dump(SVC_GOOD, f, indent=1)
with open("fixtures/r12_bad.json", "w", encoding="utf-8") as f:
    json.dump(SVC_BAD, f, indent=1)
print(f"wrote fixtures/: good + {len(MUTATIONS) + 1} bad")

if __name__ == "__main__":
    pass
