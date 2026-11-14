# Distributed Fleet Architecture: Orchestration & Multi-Node Staging/Prod

In enterprise release engineering, software is never deployed directly to production. It follows an automated promotion hierarchy:

$$\text{Build / Test (CI Node)} \longrightarrow \text{Staging (Pre-Prod Gate)} \longrightarrow \text{Production (Live Exchange Target)}$$

By integrating your **Samsung laptop** into the topology alongside your **HP Spectre** and **Raspberry Pi**, you create a genuine distributed three-node infrastructure cluster on your home network.

---

## 1. Machine Roles in Your Fleet

```
               [HP-Spectre]
       (Dev Workstation & Ansible Controller)
                 Fedora / x86_64
                 IP: 192.168.1.167
                        |
            +-----------+-----------+
            | (SSH/SCP)             | (SSH/SCP)
            v                       v
     [Samsung Laptop]        [Raspberry Pi]
      STAGING CLUSTER          PROD CLUSTER
      Linux / Windows          Debian / aarch64
         Node: stage             Node: prod
```

| Node Role | Physical Machine | OS & Architecture | Network Responsibility |
| :--- | :--- | :--- | :--- |
| **Control Node (CI/CD)** | **HP-Spectre** | Fedora (`x86_64`) | Runs tests, compiles wheels, executes Ansible playbooks, coordinates promotion. |
| **Staging Target** | **Samsung Laptop** | Linux/WSL/Ubuntu | Target for canary releases, integration verification, and staging smoke tests. |
| **Production Target** | **Raspberry Pi** | Debian (`aarch64`) | Final live target running `order-service` as an active `systemd` daemon on port 8080. |

---

## 2. Why Ansible for Multi-Node Fleet Management?

While our bash script `deploy_to_prod.sh` works well for a single machine, bash becomes fragile when managing multiple machines:
* What if one machine is offline?
* What if Staging runs Ubuntu and Prod runs Debian?
* How do you avoid duplicating 50 lines of SSH commands for every new server added to the company?

**Ansible** solves this through three core principles:
1. **Agentless (SSH Only):** No background agent or software daemon is installed on the target nodes. It communicates purely over standard SSH using Python.
2. **Idempotence:** An Ansible task only makes changes if the target state differs from the desired state (e.g., if a virtualenv already exists with the right package version, it skips re-installing).
3. **Inventory Separation:** Machines are grouped into environments (`[staging]`, `[prod]`, `[all]`), allowing you to deploy to Staging first, verify, and then promote to Prod with a single parameter.

---

## 3. The 3-Step Setup Plan for Today

1. **Discovery & SSH Key Exchange:** Power on the Samsung laptop, determine its OS, IP address, and username, and establish passwordless SSH key authentication from the HP Spectre.
2. **Construct the Ansible Workspace:** Build an `inventory.ini` and a modular playbook (`site.yml`) on your HP Spectre.
3. **Execute Multi-Node Ping & Orchestrated Deployment:** Run Ansible ad-hoc commands across the entire fleet (`ansible all -m ping`) and promote `order_service` across both nodes automatically.
