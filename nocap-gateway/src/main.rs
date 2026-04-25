// Owner: CLAUDE — Phase 2 task T2.8
//
// Minimal Axum scaffold. T2.9 mounts POST /verify-impl, T2.10 mounts the
// Slack endpoints, T2.15 fans out to Discord. For now: a single GET /health
// route so cloudflared can probe the tunnel and acceptance can be verified
// with `curl localhost:8787/health`.

use axum::{routing::get, Router};
use tracing_subscriber::EnvFilter;

const BIND_ADDR: &str = "0.0.0.0:8787";

async fn health() -> &'static str {
    "ok"
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    let app = Router::new().route("/health", get(health));

    let listener = tokio::net::TcpListener::bind(BIND_ADDR).await?;
    tracing::info!(addr = %BIND_ADDR, "nocap-gateway listening");
    axum::serve(listener, app).await?;
    Ok(())
}
