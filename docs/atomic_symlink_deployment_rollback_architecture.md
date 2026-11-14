# Atomic Symlink Deployments & Instant Rollback Architecture

In high-throughput, mission-critical environments (financial exchanges, core banking, telecom routing), software is never overwritten in place. We decouple **installation** from **activation** using filesystem symlinks.

---

## 1. Directory Topology on Target Nodes

On each target host (Samsung Staging & Raspberry Pi Prod), `/opt/order_service` is partitioned into:

```text
/opt/order_service/
├── releases/
│   ├── 0.1.0/                  # Release v0.1.0 runtime sandbox
│   │   ├── bin/order-service-daemon
│   │   └── lib/python3.11/...
│   └── 0.2.0/                  # Release v0.2.0 runtime sandbox
│       ├── bin/order-service-daemon
│       └── lib/python3.11/...
│
├── current -> /opt/order_service/releases/0.2.0    # Active Pointer
└── previous -> /opt/order_service/releases/0.1.0   # Rollback Pointer
```

---

## 2. The Mechanics of an Atomic Cutover

Linux filesystems (ext4, XFS, Btrfs) guarantee that updating a symbolic link using `ln -sfn` or `mv -T` is an atomic system call (`rename(2)`):

```bash
# 1. Point the temporary staging link to the new release
ln -sfn "/opt/order_service/releases/${NEW_VERSION}" /opt/order_service/current_tmp

# 2. Atomically swap current_tmp to current (replaces the pointer in a single kernel op)
mv -Tf /opt/order_service/current_tmp /opt/order_service/current
```

### Why This Matters:
1. **Zero In-Flight Corruption:** The daemon process and kernel file descriptors never read partially unpacked files.
2. **Immutable History:** Releases are immutable directories. Old versions remain pristine on disk.
3. **Instant Rollback:**
   ```bash
   # Revert to previous version instantly
   ln -sfn /opt/order_service/previous /opt/order_service/current
   sudo systemctl restart order-service
   ```
   **Recovery time (MTTR): $< 500\text{ ms}$.**

---

## 3. The 3-Node Promotion & Rollback State Machine

```text
       [HP-Spectre Controller]
                 |
                 +---> 1. Build Versioned Artifact (e.g., v0.2.0)
                 |
                 +---> 2. Stage to /opt/order_service/releases/0.2.0 (Samsung)
                 |
                 +---> 3. Atomically flip symlink & restart daemon on Staging
                 |
                 +---> 4. Run Staging Verification Gate
                             |
                   +---------+---------+
                   |                   |
               [FAIL]               [PASS]
                   |                   |
         Trigger Auto-Rollback         +---> 5. Promote to Production (RPi)
         Symlink -> previous           |
         Halt Pipeline                 +---> 6. Flip symlink & restart on Prod
                                       |
                                       +---> 7. Run Prod Live Gate
                                                   |
                                         +---------+---------+
                                         |                   |
                                     [FAIL]               [PASS]
                                         |                   |
                               Trigger Prod Rollback     Release Locked
                               Symlink -> previous       Complete!
```
