import json
import os
import random
import time
from contextlib import closing

import psycopg2
import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg2.extras import RealDictCursor


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://metrics:metrics@metrics-db:5432/metrics",
)
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")
KONG_PROXY_URL = os.getenv("KONG_PROXY_URL", "http://kong:8000").rstrip("/")
KONG_STATUS_URL = os.getenv("KONG_STATUS_URL", "http://kong:8100/status/ready")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://grafana:3000").rstrip("/")
METRIC_LOOKBACK_MINUTES = int(os.getenv("METRIC_LOOKBACK_MINUTES", "10"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "8"))
OLLAMA_BASE_URL = OLLAMA_URL.removesuffix("/api/generate")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS route_metrics (
  id SERIAL PRIMARY KEY,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  service_name TEXT NOT NULL,
  route_name TEXT NOT NULL,
  request_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
  avg_latency_ms DOUBLE PRECISION,
  p95_latency_ms DOUBLE PRECISION,
  kong_latency_ms DOUBLE PRECISION,
  upstream_latency_ms DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_route_metrics_captured_at
  ON route_metrics (captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_route_metrics_route_name
  ON route_metrics (route_name, captured_at DESC);
"""

app = FastAPI(title="Latency Chatbot API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def ensure_schema():
    with closing(get_db_connection()) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)


@app.on_event("startup")
def startup():
    ensure_schema()


import math

def safe_float(val):
    if val is None:
        return 0.0
    f = float(val)
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return f

def normalize_metric_row(row):
    return {
        "service_name": row["service_name"],
        "route_name": row["route_name"],
        "request_rate": safe_float(row["request_rate"]),
        "avg_latency_ms": safe_float(row["avg_latency_ms"]),
        "p95_latency_ms": safe_float(row["p95_latency_ms"]),
        "kong_latency_ms": safe_float(row["kong_latency_ms"]),
        "upstream_latency_ms": safe_float(row["upstream_latency_ms"]),
        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
    }


def fetch_recent_metrics(minutes, limit):
    try:
        ensure_schema()
        with closing(get_db_connection()) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        service_name,
                        route_name,
                        AVG(request_rate) AS request_rate,
                        AVG(avg_latency_ms) AS avg_latency_ms,
                        MAX(p95_latency_ms) AS p95_latency_ms,
                        AVG(kong_latency_ms) AS kong_latency_ms,
                        AVG(upstream_latency_ms) AS upstream_latency_ms,
                        MAX(captured_at) AS last_seen
                    FROM route_metrics
                    WHERE captured_at >= NOW() - (%s * INTERVAL '1 minute')
                    GROUP BY service_name, route_name
                    ORDER BY AVG(avg_latency_ms) DESC NULLS LAST, AVG(request_rate) DESC
                    LIMIT %s
                    """,
                    (minutes, limit),
                )
                rows = cursor.fetchall()

        return [normalize_metric_row(row) for row in rows]
    except psycopg2.Error as db_exc:
        print(f"Database error in fetch_recent_metrics: {db_exc}")
        return []
    except Exception as exc:
        print(f"Unexpected error in fetch_recent_metrics: {exc}")
        return []


def fetch_snapshot_count(minutes):
    with closing(get_db_connection()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM route_metrics
                WHERE captured_at >= NOW() - (%s * INTERVAL '1 minute')
                """,
                (minutes,),
            )
            return cursor.fetchone()[0]


def build_summary(metrics, minutes):
    if not metrics:
        return {
            "window_minutes": minutes,
            "route_count": 0,
            "sample_count": fetch_snapshot_count(minutes),
            "slowest_route": None,
            "busiest_route": None,
        }

    slowest_route = metrics[0]
    busiest_route = max(metrics, key=lambda item: item["request_rate"])

    return {
        "window_minutes": minutes,
        "route_count": len(metrics),
        "sample_count": fetch_snapshot_count(minutes),
        "slowest_route": slowest_route,
        "busiest_route": busiest_route,
    }


def build_no_data_message():
    return (
        "ยังไม่มีข้อมูล latency ในฐานข้อมูลตอนนี้ "
        "ให้ apply ไฟล์ kong/kong.yml ไปที่ Konnect control plane, "
        "ยิง traffic ผ่าน http://localhost:8000/api/... แล้วรอ metrics-worker เก็บ snapshot รอบถัดไป"
    )


def build_local_answer(question, summary):
    slowest_route = summary["slowest_route"]
    busiest_route = summary["busiest_route"]
    minutes = summary["window_minutes"]

    if not slowest_route:
        return build_no_data_message()

    parts = [
        (
            f"ช่วง {minutes} นาทีล่าสุด route ที่ช้าที่สุดคือ "
            f"{slowest_route['route_name']} "
            f"(service {slowest_route['service_name']})"
        ),
        (
            f"average latency {slowest_route['avg_latency_ms']:.2f} ms, "
            f"p95 {slowest_route['p95_latency_ms']:.2f} ms, "
            f"request rate {slowest_route['request_rate']:.3f} req/s"
        ),
    ]

    if busiest_route:
        parts.append(
            (
                f"route ที่ traffic สูงสุดคือ {busiest_route['route_name']} "
                f"ที่ {busiest_route['request_rate']:.3f} req/s"
            )
        )

    lower_question = question.lower()
    if "kong" in lower_question:
        parts.append(
            f"Kong overhead ของ route ที่ช้าที่สุดอยู่ที่ "
            f"{slowest_route['kong_latency_ms']:.2f} ms"
        )
    if "upstream" in lower_question:
        parts.append(
            f"upstream latency ของ route ที่ช้าที่สุดอยู่ที่ "
            f"{slowest_route['upstream_latency_ms']:.2f} ms"
        )

    return ". ".join(parts)


def ask_ollama(question, summary, top_routes):
    prompt = f"""
คุณคือผู้ช่วย DevOps ที่ตอบจากข้อมูลจริงเท่านั้น
ตอบเป็นภาษาไทยแบบกระชับ
ห้ามเดาตัวเลขที่ไม่มีในข้อมูล

คำถามผู้ใช้:
{question}

สรุป metrics:
{json.dumps(summary, ensure_ascii=False)}

top routes:
{json.dumps(top_routes, ensure_ascii=False)}
""".strip()

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    answer = (payload.get("response") or "").strip()
    if not answer:
        raise RuntimeError("Ollama returned an empty response.")
    return answer


def check_http_service(name, url):
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        return {
            "name": name,
            "ok": response.ok,
            "status_code": response.status_code,
            "url": url,
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "status_code": None,
            "url": url,
            "error": str(exc),
        }


def ensure_path(path):
    return path if path.startswith("/") else f"/{path}"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/system/status")
def system_status():
    services = {
        "kong_status_api": check_http_service("kong_status_api", KONG_STATUS_URL),
        "prometheus": check_http_service("prometheus", f"{PROMETHEUS_URL}/-/ready"),
        "grafana": check_http_service("grafana", f"{GRAFANA_URL}/api/health"),
        "ollama": check_http_service("ollama", f"{OLLAMA_BASE_URL}/api/tags"),
    }

    try:
        with closing(get_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM route_metrics")
                row_count = cursor.fetchone()[0]
        services["database"] = {"name": "database", "ok": True, "rows": row_count}
    except Exception as exc:
        services["database"] = {
            "name": "database",
            "ok": False,
            "error": str(exc),
        }

    return {"services": services}


@app.get("/probe/kong")
def probe_kong(path: str = Query("/api/health")):
    target_path = ensure_path(path)
    target_url = f"{KONG_PROXY_URL}{target_path}"

    try:
        response = requests.get(target_url, timeout=REQUEST_TIMEOUT_SECONDS)
        return {
            "ok": response.ok,
            "status_code": response.status_code,
            "url": target_url,
            "body": response.text[:1000],
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "url": target_url,
            "error": str(exc),
        }


@app.get("/generate-traffic")
def generate_traffic(
    count: int = Query(20, ge=1, le=200),
    path: str = Query("/api/demo/random?min_ms=75&max_ms=900"),
):
    target_path = ensure_path(path)
    target_url = f"{KONG_PROXY_URL}{target_path}"
    success_count = 0
    error_count = 0
    durations = []
    last_status_code = None

    for _ in range(count):
        started_at = time.perf_counter()
        try:
            response = requests.get(target_url, timeout=30)
            last_status_code = response.status_code
            if response.ok:
                success_count += 1
            else:
                error_count += 1
        except Exception:
            error_count += 1
        finally:
            durations.append((time.perf_counter() - started_at) * 1000)

    average_client_latency_ms = sum(durations) / len(durations)

    return {
        "url": target_url,
        "count": count,
        "success_count": success_count,
        "error_count": error_count,
        "last_status_code": last_status_code,
        "average_client_latency_ms": round(average_client_latency_ms, 2),
        "hint": (
            "ถ้าได้ 404 ให้ตรวจว่า apply kong/kong.yml ไปยัง Konnect control plane แล้วหรือยัง"
        ),
    }


@app.get("/metrics/top-latency")
def top_latency(
    minutes: int = Query(METRIC_LOOKBACK_MINUTES, ge=1, le=120),
    limit: int = Query(5, ge=1, le=20),
):
    metrics = fetch_recent_metrics(minutes, limit)
    return {
        "window_minutes": minutes,
        "items": metrics,
        "message": build_no_data_message() if not metrics else None,
    }


@app.get("/metrics/summary")
def metrics_summary(
    minutes: int = Query(METRIC_LOOKBACK_MINUTES, ge=1, le=120),
    limit: int = Query(5, ge=1, le=20),
):
    metrics = fetch_recent_metrics(minutes, limit)
    summary = build_summary(metrics, minutes)
    return {
        "summary": summary,
        "top_routes": metrics,
        "message": build_no_data_message() if not metrics else None,
    }


@app.get("/ask")
def ask_latency(
    question: str = Query("API ไหน latency สูงสุดใน 10 นาทีล่าสุด"),
    minutes: int = Query(METRIC_LOOKBACK_MINUTES, ge=1, le=120),
):
    top_routes = fetch_recent_metrics(minutes, 5)
    summary = build_summary(top_routes, minutes)
    local_answer = build_local_answer(question, summary)
    used_ollama = False
    final_answer = local_answer

    if top_routes:
        try:
            final_answer = ask_ollama(question, summary, top_routes)
            used_ollama = True
        except requests.exceptions.RequestException as req_exc:
            print(f"Ollama connection error: {req_exc}")
            final_answer = f"{local_answer} (หมายเหตุ: ไม่สามารถเชื่อมต่อ Ollama ได้ในขณะนี้ จึงใช้การวิเคราะห์แบบ Local แทน)"
            used_ollama = False
        except Exception as exc:
            print(f"Ollama error: {exc}")
            final_answer = f"{local_answer} (หมายเหตุ: เกิดข้อผิดพลาดในการประมวลผล AI)"
            used_ollama = False

    return {
        "question": question,
        "answer": final_answer,
        "used_ollama": used_ollama,
        "summary": summary,
        "top_routes": top_routes,
    }


def sleep_and_reply(kind, delay_ms):
    time.sleep(delay_ms / 1000)
    return {
        "kind": kind,
        "simulated_delay_ms": delay_ms,
        "message": f"{kind} response completed",
    }


@app.get("/demo/fast")
def demo_fast(delay_ms: int = Query(80, ge=10, le=2000)):
    return sleep_and_reply("fast", delay_ms)


@app.get("/demo/slow")
def demo_slow(delay_ms: int = Query(900, ge=10, le=10000)):
    return sleep_and_reply("slow", delay_ms)


@app.get("/demo/random")
def demo_random(
    min_ms: int = Query(50, ge=10, le=5000),
    max_ms: int = Query(1200, ge=10, le=10000),
):
    effective_min = min(min_ms, max_ms)
    effective_max = max(min_ms, max_ms)
    delay_ms = random.randint(effective_min, effective_max)
    return sleep_and_reply("random", delay_ms)
