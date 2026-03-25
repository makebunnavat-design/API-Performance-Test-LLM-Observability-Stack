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
