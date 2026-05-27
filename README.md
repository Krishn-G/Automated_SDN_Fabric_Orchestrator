# Automated SDN Fabric Orchestrator

A Python-based SDN controller that automates end-to-end provisioning of a network fabric on **Juniper SRX series** devices operating as routers. Starting from a bare set of connected devices, the orchestrator enables topology discovery, assigns fabric IP addresses, computes optimal paths, and deploys static routes — all over NETCONF without touching the CLI.

Tested on a **40-router lab fabric** at the University of Maryland.

---

## Overview

Provisioning a fabric manually means SSH-ing into every device in sequence: enabling discovery protocols, assigning point-to-point addresses, calculating next-hops by hand, and pushing routes one router at a time. On a 40-node fabric that's hundreds of individual steps, each one an opportunity for human error.

This controller automates the full workflow using **Junos PyEZ** (NETCONF) and a custom Dijkstra implementation, reducing provisioning to a single command that completes consistently regardless of fabric size.

---

## Architecture & Workflow

`SDN_Controller.py` runs the following pipeline in sequence:

```
1. LLDP Setup    →  Enable LLDP on all fabric-facing interfaces across all routers
2. Topology      →  Query LLDP neighbors; build a weighted N×N adjacency matrix
3. Networks      →  Collect customer-facing prefixes from inet.0 on each router
4. Addressing    →  Allocate /30 subnets per link; push IP assignments to all devices
5. Routing       →  Run Dijkstra per (source, destination) pair; deploy static routes
```

The management interface (`ge-0/0/0`) is excluded at every stage. Routing is only computed for **customer-facing prefixes** — fabric/underlay addresses are never injected into the routing table.

---

## Repository Structure

```
Automated_SDN_Fabric_Orchestrator/
│
├── SDN_Controller.py       # Entry point — orchestrates the full pipeline
├── LLDP_Setup.py           # Enables LLDP on fabric interfaces via Jinja2 template
├── Topology.py             # Discovers neighbors via LLDP; builds weighted adjacency matrix
├── Networks.py             # Collects customer routes from inet.0; filters out fabric interfaces
├── Addressing.py           # Allocates /30 subnets to links; pushes IP configs to devices
├── Routing.py              # Next-hop computation using NetworkX shortest-path
├── Routing_Manual.py       # Next-hop computation using a custom Dijkstra implementation
├── CostTest.py             # Standalone utility to verify link cost calculation
└── Config_Files/           # Jinja2 configuration templates for Junos
    ├── LLDP_Setup.conf
    ├── IP_Assignment.conf
    └── Static_Routing.conf
```

---

## Module Details

### `LLDP_Setup.py`
Connects to every device in `dlist` and loads `LLDP_Setup.conf` via PyEZ's `Config.load()`, enabling LLDP on the specified fabric interfaces. Changes are committed immediately. The management port (`ge-0/0/0`) is not included in the interface list and remains unaffected.

### `Topology.py`
- Calls `get_lldp_neighbors_information()` on each router to discover adjacencies.
- Skips any neighbor entry seen on `ge-0/0/0` (management).
- Calls `get_interface_information()` to read interface speed, then computes link cost as `100000 / speed_Mbps` — consistent with OSPF reference bandwidth convention.
- Returns an **N×N adjacency matrix** where `matrix[i][j] = (local_intf, remote_intf, cost)` for a live link, or `None` for no direct connection.

### `Networks.py`
- Opens `inet.0` on each router via `get_route_information()` and iterates all active routes.
- **Filters out** any route whose outgoing interface matches the fabric interface list (`ge-0/0/0` through `ge-0/0/5`), retaining only customer-facing prefixes.
- Returns `{router_index: [prefix, ...]}` — the set of destinations each router is responsible for.

### `Addressing.py`
- Iterates the **upper triangle** of the adjacency matrix to find every unique link (avoids double-allocating symmetric entries).
- Carves sequential `/30` subnets out of a configurable base subnet (default: `172.16.1.0/24`) and assigns `.1` to the local side and `.2` to the remote side of each link.
- Pushes IP assignments to each device via `IP_Assignment.conf`.

### `Routing_Manual.py` (used in production pipeline)
- Implements **Dijkstra's algorithm from scratch** over the adjacency matrix — no external graph library dependency for the core routing logic.
- For every `(source_router, target_router)` pair where the target has customer routes, computes the shortest path and extracts the next-hop IP from `Router_IPs`.
- Deploys the resulting static routes to all devices via `Static_Routing.conf`.

### `Routing.py` (alternate)
- Same logic as `Routing_Manual.py` but delegates shortest-path computation to **NetworkX** (`nx.shortest_path()` with Dijkstra).

### `CostTest.py`
Standalone script used during development to validate that `Extract_Speed()` correctly parses Junos interface speed strings (e.g., `"1000mbps"`, `"10Gbps"`) and that the cost formula produces expected values.

---

## Prerequisites

**Hardware**
- Juniper SRX series devices configured as routers
- Management network reachability to all devices
- NETCONF enabled on each device:
  ```
  set system services netconf ssh
  ```
- A user account with configuration commit privileges

**Python Dependencies**

```bash
pip install junos-eznc       # Junos PyEZ — NETCONF device management
pip install lxml             # XML parsing for RPC responses
pip install networkx         # Required only if using Routing.py (NetworkX variant)
pip install python-dotenv    # Loads credentials from .env file
```

---

## Configuration

Credentials and device addresses are loaded from a `.env` file — **never hardcode them in source**.

**`.env`** (never committed — add to `.gitignore`):
```env
FABRIC_USER=your_username
FABRIC_PASSWORD=your_password
ROUTER_1=192.168.x.x
ROUTER_2=192.168.x.x
ROUTER_3=192.168.x.x
# Add ROUTER_N entries for each device
```

**`.env.example`** (safe to commit — documents expected keys):
```env
FABRIC_USER=
FABRIC_PASSWORD=
ROUTER_1=
ROUTER_2=
```

**`.gitignore`** — ensure this line is present:
```
.env
```

`SDN_Controller.py` reads the device list at runtime:
```python
load_dotenv()
user     = os.getenv("FABRIC_USER")
password = os.getenv("FABRIC_PASSWORD")
hosts    = [v for k, v in sorted(os.environ.items()) if k.startswith("ROUTER_")]
dlist    = [Device(host=h, user=user, password=password) for h in hosts]
```

To change the fabric address space, update `base_subnet` in `Addressing.py`:
```python
def Define_IP(matrix, base_subnet="172.16.1.0/24"):
```

---

## Usage

```bash
python SDN_Controller.py
```

The controller will connect to all devices and run the full provisioning pipeline: LLDP enablement → topology discovery → customer route collection → IP assignment → route deployment.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `/30` subnets for fabric links | Minimizes address waste on point-to-point links; each subnet provides exactly 2 usable host addresses |
| OSPF-style link cost (`100000 / speed_Mbps`) | Standard IGP reference bandwidth convention; ensures higher-bandwidth paths are preferred automatically |
| Upper-triangle matrix iteration in `Addressing.py` | The adjacency matrix is symmetric — iterating only `[i][j]` where `j > i` prevents allocating two different subnets to the same physical link |
| Custom Dijkstra in `Routing_Manual.py` | Eliminates the NetworkX dependency from the core production path; makes the routing logic fully transparent and auditable |
| Route computation scoped to customer prefixes only | `Networks.py` filters `inet.0` to exclude routes reachable via fabric interfaces, so Dijkstra only runs for prefixes that actually need to be distributed. This reduces algorithm iterations significantly on large fabrics and, as a secondary benefit, prevents fabric/underlay subnets from being advertised beyond their intended scope — limiting the blast radius if a device is misconfigured or compromised |
| Management interface excluded at every stage | `ge-0/0/0` is skipped in LLDP setup, topology discovery, and route filtering — ensuring the out-of-band management plane is never mixed into fabric operations |
| Credentials externalized to `.env` | Keeps device IPs, usernames, and passwords out of version control entirely |

---

## Tech Stack

- **Python 3**
- **Junos PyEZ** (`junos-eznc`) — NETCONF-based Junos device automation
- **lxml** — XML parsing of Junos RPC responses
- **Jinja2** — Templated Junos configuration generation
- **ipaddress** (stdlib) — Subnet allocation and IP arithmetic
- **NetworkX** (optional) — Graph-based shortest-path in `Routing.py`

---

## License

MIT License — see [LICENSE](LICENSE) for details.