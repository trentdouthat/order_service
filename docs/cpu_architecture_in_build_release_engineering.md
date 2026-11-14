# CPU Architecture in Build & Release Engineering: Interpreted vs. Compiled

When orchestrating a fleet containing **`x86_64` (Intel/AMD)** and **`aarch64` (ARM64)** processors, release engineers must distinguish between **application code portability** and **system runtime dependencies**.

---

## 1. Why Our Pure Python Wheel Worked Universally

Python wheels follow the standard PEP 427 naming convention:
```
{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
```

Our build artifact was:
```
order_service-0.1.0-py3-none-any.whl
```

* **`py3`**: Any Python 3 compatible interpreter.
* **`none`**: No C-extensions; no CPython C-API binding.
* **`any`**: Valid for **any** hardware architecture.

Because `order_service` only used the standard library and pure Python, **the exact same `.whl` binary artifact was installed on both Intel (`x86_64`) and Raspberry Pi (`aarch64`) without recompilation.**

---

## 2. Where CPU Architecture DOES Matter in Interpreted Languages

Even in Python, architecture becomes a hard gate the moment you include **compiled C extensions** (e.g., `numpy`, `cryptography`, `uvloop`, or Cboe's internal C++ market data bindings):

### A. Architecture-Specific Wheels
If a package contains compiled C/C++ code, the compiler produces machine code for that specific CPU instruction set:

* **Intel/AMD Staging Node:**
  ```text
  cryptography-42.0.5-cp311-cp311-manylinux_2_28_x86_64.whl
  ```
* **Raspberry Pi Prod Node:**
  ```text
  cryptography-42.0.5-cp311-cp311-manylinux_2_28_aarch64.whl
  ```

If you copy an `x86_64` wheel to an `aarch64` Raspberry Pi and try to run it, the Linux kernel fails immediately with:
```text
OSError: /opt/order_service/.../foo.so: cannot open shared object file: Exec format error
```
`Exec format error` (Linux errno 8 / `ENOEXEC`) is the operating system telling you: *"You fed ARM CPU cores an Intel x86 machine instruction stream."*

---

## 3. Where Did We Differentiate Architecture in Today's Pipeline?

In today's Ansible pipeline, architecture was handled at **two specific layers**:

### 1. In the Operating System Runtimes (Pre-Installed)
The Python virtual environments were created by the **native system Python** on each node:
* On the Samsung (`x86_64`), `/usr/bin/python3` is an `x86_64` ELF binary.
* On the Raspberry Pi (`aarch64`), `/usr/bin/python3` is an `aarch64` ELF binary.

When Ansible executed:
```yaml
- name: Create Python virtual environment if not present
  ansible.builtin.command:
    cmd: "/usr/bin/python3 -m venv {{ install_dir }}"
```
Ansible used the host's native, architecture-specific Python engine to create the sandbox. The pure-Python code was then executed by each node's native engine.

### 2. In Ansible Telemetry & Validation (`ansible_facts`)
Ansible gathered facts during the initial discovery step:
```text
Connected to samsung (Fedora on x86_64)
Connected to rpi (Debian on aarch64)
```
In heterogeneous enterprise fleets, this fact allows playbooks to branch conditionally:

```yaml
- name: Install Architecture-Specific Low-Latency Network Drivers
  ansible.builtin.package:
    name: "{{ 'solarflare-onload-x86_64' if ansible_facts['architecture'] == 'x86_64' else 'onload-arm64' }}"
  when: environment_tier == 'prod'
```

---

## 4. The Cboe Context: How C++ Trading Systems Handle This

At an exchange like Cboe, the matching engine core is written in **C++20**:

1. **Compilation Matrix:** You cannot build once and ship `any`. The CI pipeline runs **cross-compilation matrices** using tools like GCC, Clang, or CMake toolchain files.
2. **Artifact Repository:** The build step generates two distinct native artifacts:
   * `cboe-engine-2.4.0-linux-x86_64.tar.gz`
   * `cboe-engine-2.4.0-linux-aarch64.tar.gz`
3. **Targeted Promotion:** The deployment pipeline reads the target architecture fact and distributes the corresponding machine binary to the correct hardware tier.
