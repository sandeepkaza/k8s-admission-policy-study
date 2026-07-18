# Paper 2 cloud leg: run engine benchmark on EKS (dr-eks), engines in isolation.
# Outputs cloud-eks_verify_*.csv / cloud-eks_latency_*.csv. Logs to bench-eks.log.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$kc = "kubectl"
$ctx = "dr-eks"
$sp = "."  # dir holding gatekeeper-install.yaml / kyverno-install.yaml
$log = "bench-eks.log"
"BENCH EKS START $(Get-Date -Format o)" | Add-Content $log

function Bench($engine) {
    "== bench $engine $(Get-Date -Format o)" | Add-Content $log
    python bench.py --engine $engine --phase both --kubecontext $ctx --out-prefix cloud-eks_ 2>&1 | Add-Content $log
    if ($LASTEXITCODE -ne 0) { "BENCH $engine FAILED" | Add-Content $log; exit 1 }
}

# 1. baseline
Bench baseline

# 2. VAP (native, no install)
& $kc --context $ctx apply -f engines/vap.yaml 2>&1 | Add-Content $log
Start-Sleep 15
Bench vap
& $kc --context $ctx delete -f engines/vap.yaml 2>&1 | Add-Content $log

# 3. Gatekeeper
& $kc --context $ctx apply -f "$sp\gatekeeper-install.yaml" 2>&1 | Add-Content $log
& $kc --context $ctx -n gatekeeper-system rollout status deploy/gatekeeper-controller-manager --timeout=300s 2>&1 | Add-Content $log
& $kc --context $ctx apply -f engines/gatekeeper.yaml 2>&1 | Add-Content $log
Start-Sleep 20
& $kc --context $ctx apply -f engines/gatekeeper-constraints.yaml 2>&1 | Add-Content $log
Start-Sleep 30
Bench gatekeeper
& $kc --context $ctx delete -f engines/gatekeeper-constraints.yaml --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $ctx delete -f engines/gatekeeper.yaml --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $ctx delete -f "$sp\gatekeeper-install.yaml" --ignore-not-found 2>&1 | Add-Content $log

# 4. Kyverno
& $kc --context $ctx apply -f "$sp\kyverno-install.yaml" --server-side 2>&1 | Add-Content $log
& $kc --context $ctx -n kyverno rollout status deploy/kyverno-admission-controller --timeout=300s 2>&1 | Add-Content $log
Start-Sleep 10
& $kc --context $ctx apply -f engines/kyverno.yaml 2>&1 | Add-Content $log
Start-Sleep 20
Bench kyverno
& $kc --context $ctx delete -f engines/kyverno.yaml --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $ctx delete -f "$sp\kyverno-install.yaml" --ignore-not-found 2>&1 | Add-Content $log
# known gotcha: kyverno uninstall leaves dynamic webhook configs behind
& $kc --context $ctx delete validatingwebhookconfigurations -l webhook.kyverno.io/managed-by=kyverno --ignore-not-found 2>&1 | Add-Content $log
& $kc --context $ctx delete mutatingwebhookconfigurations -l webhook.kyverno.io/managed-by=kyverno --ignore-not-found 2>&1 | Add-Content $log

# leave cluster clean for Paper 3 DR trials
& $kc --context $ctx get validatingwebhookconfigurations,mutatingwebhookconfigurations 2>&1 | Add-Content $log
"BENCH EKS DONE $(Get-Date -Format o)" | Add-Content $log
