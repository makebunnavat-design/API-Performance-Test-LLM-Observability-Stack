<div align="center">
  <h1>🚀 Enterprise API Gateway & LLM Observability Stack</h1>
  <p>A full-stack, production-ready observability system built around <b>Kong Gateway</b> and <b>Ollama (Local LLMs)</b> to monitor, secure, and analyze traffic for an AI-powered Repair Assistance system.</p>
</div>

---

## 📌 Project Overview
This project demonstrates the implementation of a modern **API Management and Observability Architecture**. It acts as the gateway and monitoring infrastructure for a heavy LLM backend (Repair Chatbot), allowing for precise latency tracking, traffic generation, and visual analytics without exposing the backend directly.

### 🌟 Key Features
- **Centralized API Gateway**: Utilizes **Kong Gateway (Konnect)** as the primary data plane to proxy traffic and enforce rate-limiting/security.
- **Real-Time Observability**: Employs **Prometheus** to scrape `/metrics` from Kong, tracking HTTP status codes, bandwidth, and millisecond-level latency.
- **Data Engineering**: A custom Python `metrics-worker` polls Prometheus periodically and stores historical snapshots in **PostgreSQL**.
- **Interactive AI Analytics**: Features a **FastAPI** backend that natively interfaces with **Ollama (`phi3:mini`)** to automatically generate human-readable latency reports based on database snapshots!
- **Control Room Dashboard**: A lightweight frontend GUI (`HTML/JS + Nginx`) acts as the nerve center for simulating traffic, probing Kong routes, and querying the LLM safely (CORS-friendly).
- **GPU-Accelerated Local AI**: Configured Docker resources to auto-reserve NVIDIA GPUs for instant inference speeds.

---

## 🛠️ Prerequisites
Before running this stack, ensure you have the following installed:
- **Docker Desktop**: With Docker Compose support.
- **NVIDIA GPU & Drivers**: Required for Ollama acceleration (Windows/Linux).
- **NVIDIA Container Toolkit**: If running on Linux.
- **decK CLI**: For syncing Kong configurations.
- **Kong Konnect Account**: To manage the control plane.

---

## 🏗️ Architecture Design
The entire stack is containerized via `docker-compose.yml`, deploying 8 highly cohesive microservices:

1. **`kong-gateway`**: The traffic controller & metrics exporter (Port 8000).
2. **`prometheus`**: Pulls metrics from Kong's internal port (Port 9090).
3. **`grafana`**: Visualizes Prometheus data using built-in provisioned dashboards (Port 3000).
4. **`metrics-db`**: Persistent snapshot storage (`postgres:16-alpine`).
5. **`metrics-worker`**: Python ETL script transferring summarized metrics from PromQL to PostgreSQL.
6. **`ollama`**: NVIDIA GPU-accelerated local LLM inference engine.
7. **`latency-chatbot`**: **FastAPI** answering statistical questions by orchestrating PostgreSQL and Ollama (Port 18081).
8. **`latency-ui`**: Nginx web server hosting the Latency Control Room (Port 8080).

---

## 🚀 Getting Started

### 1. Start the Environment
```ps
docker compose up -d --build
```
Ensure that you pull the Ollama model:
```ps
docker exec -it ollama ollama pull phi3:mini
```

### 2. Apply Kong Configurations via decK
This project uses declarative configuration for API routes. 
```ps
$env:DECK_KONNECT_TOKEN = "your-konnect-pat"
$env:DECK_KONNECT_CONTROL_PLANE_NAME = "default"
$env:KONNECT_CONTROL_PLANE_URL = "https://us.api.konghq.com"

.\deck.exe gateway apply kong/kong.yml
```
*Note: Make sure your `tls.crt` and `tls.key` from Konnect are placed inside `kong/certs/` before starting Kong!*

### 3. Usage
- **Control Room UI**: `http://localhost:8080`
- **FastAPI Documentations**: `http://localhost:18081/docs`
- **Grafana Dashboard**: `http://localhost:3000` *(admin / admin)*

---

## 🗺️ Future Roadmap
- [ ] **Slack/Discord Integration**: Send automated alerts when P95 latency exceeds 500ms.
- [ ] **Adaptive Rate Limiting**: Automatically tighten Kong rate limits when upstream latency spikes.
- [ ] **Multi-Model Support**: Compare latency between different local models (phi3 vs llama3).
- [ ] **Historical Analytics**: Long-term trend analysis using advanced PostgreSQL window functions.

---

*This project is an excellent showcase of integrating modern API gateways with self-hosted AI models while solving the complex problem of LLM latency observability.*
