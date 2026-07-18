# Cloud-leg runner: benchmark all four engines on a managed cluster, each in
# isolation (install -> load corpus -> bench -> verified-clean uninstall).
# Usage: .\bench-eks.ps1 [-Ctx dr-eks] [-Prefix cloud-eks_]
# Requires: kubectl context for the cluster; engine install manifests are the
# upstream release YAMLs (URLs below). Logs to bench-<ctx>.log.
param(
    [string]$Ctx = "dr-eks",
    [string]$Prefix = "cloud-eks_"
)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$kc = "kubectl"
$gkUrl = "https://raw.githubusercontent.com/open-policy-agent/gatekeeper/v3.20.1/deploy/gatekeeper.yaml"
$kyUrl = "https://github.com/kyverno/kyverno/releases/download/v1.15.2/install.yaml"
$log = "bench-$Ctx.log"
"BENCH START ctx=$Ctx $(Get-Date -Format o)" | Add-Content $log

function Bench($engine) {
    "== bench $engine $(Get-Date -Format o)" | Add-Content $log
    python bench.py --engine $engine --phase both --kubecontext $Ctx --out-prefix $Prefix 2>&1 | Add-Content $log
    if ($LASTEXITCODE -ne 0) { "BENCH $engine FAILED" | Add-Content $log; exit 1 }
}

# 1. baseline (no engines)
Bench baseline

# 2. VAP (in-tree, nothing to install)
& $kc --context $Ctx apply -f engines/vap.yaml 2>&1 | Add-Content $log
Start-Sleep 15
Bench vap
& $kc --context $Ctx delete -f engines/vap.yaml 2>&1 | Add-Content $log

# 3. Gatekeeper
& $kc --context $Ctx apply -f $gkUrl 2>&1 | Add-Content $log
# Small-node clusters (<=1 GiB/node): the default 3x512Mi deployment cannot
# schedule (paper's deployability finding). Uncomment to downsize:
# & $kc --context $Ctx -n gatekeeper-system scale deploy gatekeeper-controller-manager --replicas=1
# (plus a memory-request patch to ~200Mi on controller + audit)
& $kc --context $Ctx -n gatekeeper-system rollout status deploy/gatekeeper-controller-manager --timeout=300s 2>&1 | Add-Content $log
if ($LASTEXITCODE -ne 0) { "GATEKEEPER NOT READY" | Add-Content $log; exit 1 }
& $kc --context $Ctx apply -f engines/gatekeeper.yaml 2>&1 | Add-Content $log
Start-Sleep 20
& $kc --context $Ctx apply -f engines/gatekeeper-constraints.yaml 2>&1 | Add-Content $log
Start-Sleep 30
Bench gatekeeper
& $kc --context $Ctx delete -f engines/gatekeeper-constraints.yaml --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $Ctx delete -f engines/gatekeeper.yaml --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $Ctx delete -f $gkUrl --ignore-not-found 2>&1 | Add-Content $log

# 4. Kyverno
& $kc --context $Ctx apply --server-side -f $kyUrl 2>&1 | Add-Content $log
& $kc --context $Ctx -n kyverno rollout status deploy/kyverno-admission-controller --timeout=300s 2>&1 | Add-Content $log
Start-Sleep 10
& $kc --context $Ctx apply -f engines/kyverno.yaml 2>&1 | Add-Content $log
Start-Sleep 20
Bench kyverno
& $kc --context $Ctx delete -f engines/kyverno.yaml --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $Ctx delete -f $kyUrl --ignore-not-found 2>&1 | Add-Content $log
# known gotcha: kyverno uninstall leaves dynamic webhook configs behind
& $kc --context $Ctx delete validatingwebhookconfigurations -l webhook.kyverno.io/managed-by=kyverno --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $Ctx delete mutatingwebhookconfigurations -l webhook.kyverno.io/managed-by=kyverno --ignore-not-found 2>&1 | Add-Content $log

# verify the cluster is clean for whatever runs next
& $kc --context $Ctx get validatingwebhookconfigurations,mutatingwebhookconfigurations 2>&1 | Add-Content $log
"BENCH DONE ctx=$Ctx $(Get-Date -Format o)" | Add-Content $log
