# Cboe Senior Software Engineer: Build & Release Narrative Playbook

This playbook outlines high-signal interview stories designed for your Cboe interview. Both narratives bridge mission-critical systems engineering (deterministic, low-latency releases) with intelligent automation (AI guardrails).

## Story 1: The Mission-Critical CI/CD Release Pipeline

**Core Question It Answers:** *"Walk me through the ideal release pipeline for a weekly, high-throughput financial trading system like Cboe Ti."*

### 1. Architectural Philosophy

* **Determinism & Reproducibility:** Every build artifact must be immutable, cryptographically signed, and bit-for-bit reproducible. A microsecond latency exchange engine cannot afford compiler drift or dynamically resolved dependencies at runtime.
* **Fail Fast, Shift Left:** Flaky tests, memory leaks, and interface breaks must be caught in local staging before entering the trunk.
* **Multi-Environment Promotion Hierarchy:** Build on CI runner $\longrightarrow$ Promote to Staging/Canary node $\longrightarrow$ Execute live boundary smoke tests $\longrightarrow$ Promote to Production cluster.

```
[Developer PR / Local Workstation (HP-Spectre)]
        |
        v
[Gate 1: Pre-Flight Test Suite] (Pytest / C++ GoogleTest)
        |
        v
[Gate 2: Immutable Artifact Compilation] (Python Wheel / Hermetic CMake Binary)
        |
        v
[Gate 3: Staging Cluster Deployment] (Ansible Orchestration -> Samsung Node)
        |
        v
[Gate 4: Staging Integration & Negative Boundary Smoke Gate]
  - Positive payload verification (GET /healthz, POST /validate)
  - Negative input boundary rejection (e.g. malformed symbols)
        |
        +-----> [FAILED] ---> ABORT PIPELINE (Production Untouched)
        |
        v [PASSED]
[Gate 5: Production Cluster Promotion] (Ansible Orchestration -> Raspberry Pi Node)
        |
        v
[Gate 6: Production Live Verification Gate]
  - L7 HTTP / L4 TCP socket probing
  - Daemon state inspection via systemd / journald
```

### 2. Physical Testbed Implementation (Your Real Home Lab Topology)

When discussing multi-environment deployments, you have direct, hands-on experience running this exact architecture across a heterogeneous cluster:

* **Control / CI Node:** HP-Spectre laptop (`Fedora 44`, `x86_64`) running test suites and driving Ansible orchestration.
* **Staging Cluster:** Samsung laptop (`Fedora 44`, `x86_64`) serving as the pre-production canary target with isolated systemd daemons.
* **Production Cluster:** Raspberry Pi (`Debian 12 Bookworm`, `aarch64`) running live exchange services on dedicated `/opt/` runtimes.

#### Key Engineering Takeaways from This Testbed:
1. **Heterogeneous Architecture Management:** Handling `x86_64` and `aarch64` binaries and differing user profiles (`trentdouthat` vs. `tdouthat`) using Ansible Jinja2 templates (`.j2`) rather than hardcoded bash scripts.
2. **Deterministic Networking:** Bypassing flaky UDP multicast DNS (`.local`) by codifying static host resolutions in `/etc/hosts` and Ansible inventories.
3. **Hard Stop Promotion Gating:** Codified bash logic (`promote.sh`) where a single failure on the Staging HTTP API terminates the pipeline before any production services are restarted.

---

### 3. Your Personal War Stories: 3 Battle-Tested Cutover Strategies

*When the interviewer asks: "How have you actually implemented cutovers and rollbacks in production environments?"*

1. **Multi-Region Cloud Blue/Green (AWS + ALBs):**
   > *"In our distributed cloud environments, we ran containerized services across distinct AWS regions. Deployments went live in the green region where automated health checks and synthetic transactions validated the release under zero customer load. Once green was verified healthy, we shifted traffic at the ALB layer. If unexpected latency or errors appeared, we could pivot traffic back to the blue region immediately."*

2. **Kubernetes Graceful Draining & Probing:**
   > *"For our microservice fleets running on Kubernetes, we utilized rolling deployments with strict readiness and liveness probes. We configured the orchestrator so new pods were scheduled, warmed, and verified via probe endpoints before the service mesh routed real traffic. Only after the new pods proved healthy did Kubernetes gracefully drain connections and terminate the legacy pods, ensuring zero in-flight request drops."*

3. **Bare-Metal Atomic Rollouts & Systemd Automation:**
   > *"Down at the bare-metal OS level—where virtualization introduces unacceptable latency jitter—we manage releases using dedicated runtime paths (`/opt/order_service`), immutable versioned artifacts, and systemd process supervision. We wrap this in multi-node Ansible pipelines that gate promotion: staging must pass live integration probes before the orchestrator touches production targets."*

---

## Story 2: The Production Incident, Triage, and Post-Mortem

**Core Question It Answers:** *"Tell me about a time a production release or mission-critical deployment failed. How did you triage, recover, and ensure it never happened again?"*

### The Framework: STAR-E
* **S**ituation $\rightarrow$ High stakes, time pressure, business impact.
* **T**ask $\rightarrow$ Your specific ownership and role.
* **A**ction $\rightarrow$ Methodical, calm technical diagnosis and rapid mitigation.
* **R**esult $\rightarrow$ MTTR (Mean Time to Recovery), restored stability.
* **E**valuation / Evolution $\rightarrow$ How you codified the fix into the CI/CD pipeline so it could *never* happen again.

### Narrative Script & Talking Points

#### 1. Situation & Task
> *"During a scheduled release rollout of a high-throughput backend service, the application completed its deployment, passed initial synthetic ping checks, but within 8 minutes began shedding inbound socket connections. The service error rate climbed to 15%, and downstream consumers were experiencing connection timeouts. As the release/DevOps engineer on point, my immediate priority was to stabilize production, identify the failure mode, and determine whether to patch forward or trigger an instant rollback."*

#### 2. Action (Methodical Triage)
> *"First, I avoided the trap of guessing or restarting services blindly, which can destroy active memory states and race-condition evidence:
> 1. **Containment:** I initiated our rollback protocol immediately to cut client traffic back to the previous stable blue-environment binary. Our MTTR target was under 3 minutes; traffic normalized immediately.
> 2. **Telemetry & Log Isolation:** Once production was safe, I isolated the canary node logs. Using Linux diagnostic tools (`ss -s`, `lsof -i`, and `journalctl`), I noticed socket allocations in a `CLOSE_WAIT` state accumulating until the Linux process exhausted its configured file descriptor limits (`ulimit -n`).
> 3. **Root Cause Discovery:** A newly introduced connection pool configuration had altered how keep-alive headers were handled on socket teardowns. Under high socket churn, file descriptors were leaked instead of recycled."*

#### 3. Result & Cultural Impact
> *"The immediate rollback protected downstream clients from further degradation. We conducted a blameless post-mortem with the development and infrastructure teams. The focus was not on 'who made the typo in the pool config,' but 'why did our pipeline let a file descriptor leak pass into production?'"*

#### 4. Evolution (The Long-Term Fix in the CI/CD Pipeline)
> *"To prevent recurrence, I made three permanent systemic changes to our build and release practice:
> 1. **Automated Soak & Leak Testing:** Added a 10-minute stress-testing stage to the pre-deployment pipeline that specifically monitors process open file descriptors (`/proc/$PID/fd`) and memory RSS under artificial socket churn.
> 2. **Linux System Configuration as Code:** Locked and codified `systemd` unit file resource limits (`LimitNOFILE=65536`) into Ansible templates rather than relying on manual server baselines.
> 3. **Agentic Log Triage:** Introduced an automated SRE triage tool into the test runner. When an integration run fails, the agent parses the raw systemd/journalctl logs, detects patterns like `EMFILE: Too many open files` or socket binding errors, and flags the exact root cause directly in the developer's pull request."*

---

## Key Interview Cheat Sheet: Vocabulary to Use

* **Promotion Gating** (deploy to staging, assert health/boundaries, promote to prod)
* **Idempotency** (ensuring configuration runs leave system in identical state without side effects)
* **Heterogeneous Clusters** (orchestrating across disparate OS distributions and CPU architectures like x86_64 and aarch64)
* **MTTR (Mean Time to Recovery)** & **MTTD (Mean Time to Detect)**
* **Deterministic builds** (reproducible compilation, locked dependency trees)
* **Blameless Post-Mortem** (focusing on system design over human error)
