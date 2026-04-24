---
name: infra_maintenance
description: Infrastructure maintenance and connectivity detection (config/log/alarm/memory/LLDP), executing show/display commands via the local NOC API.
metadata:
  openclaw:
    emoji: "🛠️"
---

# infra_maintenance — Infrastructure Maintenance & Connectivity Detection

Used for assessing the operational status of network devices (Huawei/Cisco/H3C): configuration, logs, alarms, memory usage, and LLDP neighbor summary.

## Parameters

- `device_name` (required): Target device name (e.g., `Core-Router-01`)
- `vendor` (required): `Huawei` | `Cisco` | `H3C`
- `question_number` (required): Number representing the current question/problem ID being solved
- `action` (required):
  - `config`: View current configuration
  - `log`: View log buffer
  - `alarm`: View active alarms
  - `memory`: View memory usage
  - `lldp`: View LLDP neighbor summary

## Execution Method (Local NOC API)

- Endpoint: `http://127.0.0.1:5000/api/agent/execute`
- Method: `POST`
- Body: `{ "device_name": "...", "command": "...", "question_number": 1 }`

### Command Mapping

```text
Huawei:
  config: display current-configuration
  log: display logbuffer
  alarm: display alarm active
  memory: display memory-usage
  lldp: display lldp neighbor brief

Cisco:
  config: show running-config
  log: show logging
  alarm: show facility-alarm status
  memory: show processes memory
  lldp: show lldp neighbors

H3C:
  config: display current-configuration
  log: display logbuffer
  alarm: display alarm active
  memory: display memory
  lldp: display lldp neighbor-list
```

### Python requests Example (Recommended)

> Note: In Windows/enterprise environments, system proxies may interfere with local `127.0.0.1` calls; `s.trust_env = False` is used here to disable environment proxies.

```python
import os
import requests

# Remove proxy environment variables to prevent interference with local API calls
for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    os.environ.pop(key, None)

s = requests.Session()
s.trust_env = False  # Do not read system/environment proxies

url = "http://127.0.0.1:5000/api/agent/execute"
body = {
    "device_name": "Core-Router-01",
    "command": "display logbuffer",
    "question_number": 1,
}

r = s.post(url, json=body, timeout=30)
r.raise_for_status()
print(r.text)
```

## Notes

- Currently designed for read-only queries (show/display) only.

## Reasoning Guide

Use this section to decide **which action to call, in what order, and how to interpret the result**.

### When to use this skill
Use `infra_maintenance` when the question involves:
- A device that is unreachable or behaving erratically (start with `lldp` or `log`)
- Suspicion of a configuration change causing a fault (use `config`)
- Detecting a hardware or resource alarm (`alarm`, `memory`)
- Topology reconstruction via LLDP when `l2_link` neighbor data is empty

### Recommended Investigation Order
1. **`lldp`** first — establish which physical neighbors the device sees. If a link that should exist is missing here, the physical layer is broken.
2. **`log`** — look for interface flap messages, protocol adjacency loss, or error logs within the last few hours.
3. **`alarm`** — check if a hardware alarm (e.g., fan failure, memory exhaustion) is the root cause of unexpected behaviour.
4. **`memory`** — if the device is slow or dropping connections, high memory utilisation (>85%) is a likely cause.
5. **`config`** — use last; compare with expected configuration to find misconfigured ACLs, missing routes, or wrong interface IPs.

### Key Signals in Output to Watch For
| Signal | Interpretation |
|---|---|
| LLDP neighbor missing for a known link | Physical link down or LLDP disabled on that port |
| Log shows repeated `interface X down/up` | Flapping link — check cabling or SFP |
| Log shows `OSPF neighbor lost` or `BGP session reset` | Control plane disruption — correlate with interface flaps |
| Alarm shows `Memory exhausted` or `CPU overload` | Device under stress — may be causing protocol drops |
| Config shows `shutdown` on an interface | Manually disabled — administrative action, not a fault |
| Config shows no route or wrong next-hop | Misconfiguration — cite the specific line in your answer |
