import os
import time

import psycopg2
import requests


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://metrics:metrics@metrics-db:5432/metrics",
)
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/")
SCRAPE_WINDOW = os.getenv("SCRAPE_WINDOW", "2m")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
PROM_QUERY_URL = f"{PROMETHEUS_URL}/api/v1/query"

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

METRIC_QUERIES = {
    "request_rate": (
        f"sum by (service, route) "
        f"(rate(kong_http_requests_total[{SCRAPE_WINDOW}]))"
    ),
    "avg_latency_ms": (
        f"sum by (service, route) "
        f"(rate(kong_request_latency_ms_sum[{SCRAPE_WINDOW}])) "
        f"/ clamp_min(sum by (service, route) "
        f"(rate(kong_request_latency_ms_count[{SCRAPE_WINDOW}])), 0.001)"
    ),
    "p95_latency_ms": (
        f"histogram_quantile(0.95, sum by (le, service, route) "
        f"(rate(kong_request_latency_ms_bucket[{SCRAPE_WINDOW}])))"
    ),
    "kong_latency_ms": (
        f"sum by (service, route) "
        f"(rate(kong_kong_latency_ms_sum[{SCRAPE_WINDOW}])) "
        f"/ clamp_min(sum by (service, route) "
        f"(rate(kong_kong_latency_ms_count[{SCRAPE_WINDOW}])), 0.001)"
    ),
    "upstream_latency_ms": (
        f"sum by (service, route) "
        f"(rate(kong_upstream_latency_ms_sum[{SCRAPE_WINDOW}])) "
        f"/ clamp_min(sum by (service, route) "
        f"(rate(kong_upstream_latency_ms_count[{SCRAPE_WINDOW}])), 0.001)"
    ),
}


def ensure_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA_SQL)


def fetch_prometheus_vector(promql):
    response = requests.get(
        PROM_QUERY_URL,
        params={"query": promql},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")

    return payload["data"]["result"]


def normalize_value(raw_value):
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def collect_snapshot():
    merged_metrics = {}

    for metric_name, promql in METRIC_QUERIES.items():
        for item in fetch_prometheus_vector(promql):
            labels = item.get("metric", {})
            service_name = labels.get("service") or "unknown-service"
            route_name = labels.get("route") or "unknown-route"
            key = (service_name, route_name)

            metric_bucket = merged_metrics.setdefault(
                key,
                {
                    "service_name": service_name,
                    "route_name": route_name,
                    "request_rate": 0.0,
                    "avg_latency_ms": None,
                    "p95_latency_ms": None,
                    "kong_latency_ms": None,
                    "upstream_latency_ms": None,
                },
            )
            metric_bucket[metric_name] = normalize_value(item["value"][1])

    return list(merged_metrics.values())


def write_snapshot(connection, snapshot_rows):
    if not snapshot_rows:
        print("No Kong metrics available yet. Waiting for routed traffic...")
        return

    rows = [
        (
            row["service_name"],
            row["route_name"],
            row["request_rate"] or 0.0,
            row["avg_latency_ms"],
            row["p95_latency_ms"],
            row["kong_latency_ms"],
            row["upstream_latency_ms"],
        )
        for row in snapshot_rows
    ]

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO route_metrics (
                service_name,
                route_name,
                request_rate,
                avg_latency_ms,
                p95_latency_ms,
                kong_latency_ms,
                upstream_latency_ms
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )

    print(f"Stored {len(rows)} route metric snapshots.")


def main():
    while True:
        try:
            with psycopg2.connect(DATABASE_URL) as connection:
                ensure_schema(connection)
                snapshot = collect_snapshot()
                write_snapshot(connection, snapshot)
        except Exception as exc:
            print(f"metrics-worker error: {exc}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
