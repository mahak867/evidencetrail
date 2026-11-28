#!/usr/bin/env bash
# Start the OpenTelemetry Demo (core services + Jaeger/Prometheus/OpenSearch) for EvidenceTrail.
#   bash otel/up.sh           fetch the demo (if needed) and start it
#   bash otel/up.sh down      stop it
# Then run EvidenceTrail with:  TARGET=oteldemo OTEL_DEMO_DIR=<demo dir> ...
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO_DIR="${OTEL_DEMO_DIR:-$HERE/../../opentelemetry-demo}"
DEMO_COMMIT="3a53fdfb7c07eebc6e9765751621fd70a76240c9"   # version EvidenceTrail was tested against (27 Nov 2026)

if [ ! -d "$DEMO_DIR/.git" ]; then
  git init -q "$DEMO_DIR"
  git -C "$DEMO_DIR" remote add origin https://github.com/open-telemetry/opentelemetry-demo.git
  git -C "$DEMO_DIR" fetch -q --depth 1 origin "$DEMO_COMMIT"
  git -C "$DEMO_DIR" checkout -q FETCH_HEAD
fi

export EVIDENCETRAIL_OTEL_DIR="$HERE"
# quay.io may be unreachable from some networks; the same images are published on Docker Hub.
export JAEGERTRACING_IMAGE="${JAEGERTRACING_IMAGE:-jaegertracing/jaeger:2.23.0}"
export PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-prom/prometheus:v3.16.0}"
# 15 simulated users (demo default: 5) so low-traffic services such as payment see a few calls a minute.
export LOCUST_USERS="${LOCUST_USERS:-15}"

cd "$DEMO_DIR"
FILES=(-f compose.yaml -f compose.observability.yaml -f "$HERE/compose.evidencetrail.yaml")
if [ "${1:-up}" = "down" ]; then
  docker compose "${FILES[@]}" down
else
  docker compose "${FILES[@]}" up -d --no-build
  echo "OpenTelemetry Demo is up. Export before running EvidenceTrail:"
  echo "  export TARGET=oteldemo OTEL_DEMO_DIR=$DEMO_DIR"
fi
