# Distributed GPU / Server Health Monitor

A lightweight, **mesh-network–style health monitor** for distributed GPU clusters.  
It handles **isolation detection** (figuring out *"am I down or is the network down?"*) and sends **Slack alerts** on crashes and recoveries.

---

## Why Use This?

- **Decentralized**  
  No central master server required. Each node participates equally.

- **Smart Alerts**  
  Distinguishes between **internet connectivity loss** and an actual **server crash**.

- **History Tracking**  
  Logs crash duration and recovery timestamps to **MongoDB**.

- **Zero Bloat**  
  Built with simple **Python + FastAPI**, minimal dependencies.

---

## Installation

### Clone the Repository

```bash
git clone <https://github.com/Annad25/gpu_monitor>
cd gpu-monitor
```

### Set Up Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your MongoDB URI and Slack Webhook
nano .env
```

---

## Run as a Linux Service (systemd)

Edit the provided `gpu_monitor.service` file to match your project paths, then:

```bash
sudo cp gpu_monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gpu_monitor
```

### Status Check

```bash
systemctl status gpu_monitor
```

---


## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
