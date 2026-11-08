# Order Service: Distributed Exchange Matching Engine & Release Pipeline

An enterprise-grade, deterministic limit order book (LOB) and order validation daemon built in Python 3.11+, complete with a multi-node, zero-downtime atomic deployment pipeline and automated rollback orchestration.

Designed to demonstrate mission-critical financial exchange principles: price-time priority (FIFO) matching, strict boundary verification, and automated release gating across a heterogeneous multi-node Linux fleet.

---

## 1. System Architecture

```
                       [HP-Spectre Controller]
                 (Fedora 44 / x86_64 / CI Testbed)
                                |
            +-------------------+-------------------+
            | (SSH / Ansible)                       | (SSH / Ansible)
            v                                       v
    [Staging Node]                          [Production Node]
  Samsung / x86_64                        Raspberry Pi / aarch64
(Canary & Integration Gate)               (Live Supervised Daemon)
```

The system separates concerns across three physical/virtual tiers:
* **CI / Orchestration Runner:** Runs pre-flight test matrices, builds hermetic wheels, and coordinates promotion.
* **Staging Cluster:** Receives atomic release cutovers and executes live positive/negative boundary smoke gates.
* **Production Fleet:** Runs active daemons under `systemd` process supervision with sub-second rollback capabilities.

---

## 2. Core Components

### A. Price-Time Priority Matching Engine (`order_service.matching_engine`)
* **Data Structures:** In-memory Limit Order Book maintaining sorted queues for Bids (descending price, ascending time) and Asks (ascending price, ascending time).
* **Execution Rule:** Trade execution prices are determined by the **resting order** on the book, guaranteeing price improvement to aggressive market participants.
* **Partial Fills & Remainder Handling:** Unfilled volume from aggressive orders transitions cleanly into resting book state without queue disruption.

### B. Ingress Boundary Validation (`order_service.validator`)
* Hardened input sanitation guarding against malformed tickers, non-numeric values, negative prices, and floating-point anomalies (IEEE-754 `NaN`, `Inf`).

### C. Zero-Downtime Atomic Symlink Deployments (`deploy_atomic.yml`)
To prevent in-flight execution corruption during upgrades:
1. Versioned releases are isolated under `/opt/order_service/releases/<version>/`.
2. An atomic pointer swap (`current -> releases/<version>`) replaces the execution path in a single filesystem inode operation (`rename(2)`), completely eliminating binary-tear race conditions.
3. A fallback link (`previous`) tracks the last known-healthy release for sub-second emergency rollbacks (`rollback.yml`).
4. Automated retention garbage collection (`cleanup_old_releases.yml`) purges stale versions while protecting active pointers.

---

## 3. Automated Quality & Promotion Gating (`promote.sh`)

Every deployment follows a strict 7-stage promotion pipeline:

| Gate | Stage | Failure Action |
| :--- | :--- | :--- |
| **Gate 1** | Local Pytest Unit Matrix (28 assertions) | Abort build |
| **Gate 2** | Immutable Wheel Build (`uv build`) | Abort build |
| **Gate 3** | Staging Atomic Symlink Cutover | Abort build |
| **Gate 4** | Staging Integration & Negative Boundary Probe | **Auto-rollback Staging; halt pipeline** |
| **Gate 5** | Production Atomic Symlink Cutover | Trigger incident response |
| **Gate 6** | Production Live Verification Probe | **Auto-rollback Production to `previous`** |
| **Gate 7** | Fleet Retention Policy Garbage Collection | Log warning; preserve active links |

---

## 4. Verification & Testing

Execute the full automated test harness:

```bash
# Run entire test suite (validator + matching engine)
uv run pytest -v

# Filter specifically for matching engine test cases
uv run pytest tests/test_matching_engine.py -v
```

### Test Coverage Highlights
* Empty book initialization and spread calculation.
* Deterministic resting order placement and cancellations.
* Full and partial execution crossing spreads.
* Price priority (cheapest ask / highest bid matches first).
* Time priority FIFO queueing at identical price boundaries.

---

## 5. Technology Stack

* **Language & Runtime:** Python 3.11+ / CPython
* **Build System & Tooling:** `uv`, `pytest`
* **Configuration & Orchestration:** Ansible 2.15+ (Agentless over SSH)
* **Process Management:** Linux `systemd`, `systemd-journald`
* **Target Platforms:** Heterogeneous Linux (`x86_64` and `aarch64` ARM)