// Owner: CLAUDE — Phase 2 task T2.8 (T2.9 wires /verify-impl)
//
// Axum perimeter. T2.10 mounts the Slack endpoints, T2.15 fans out to
// Discord. Routes live under `routes/`.

mod routes;

use axum::{
    routing::{get, post},
    Router,
};
use tracing_subscriber::EnvFilter;

const BIND_ADDR: &str = "0.0.0.0:8787";

async fn health() -> &'static str {
    "ok"
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load repo-root .env. Walks parents from cwd; harmless if missing.
    let _ = dotenvy::dotenv();

    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    let app = Router::new()
        .route("/health", get(health))
        .route("/verify-impl", post(routes::verify::verify_impl))
        .route("/slack-event", post(routes::slack::slack_event));

    let listener = tokio::net::TcpListener::bind(BIND_ADDR).await?;
    tracing::info!(addr = %BIND_ADDR, "nocap-gateway listening");
    axum::serve(listener, app).await?;
    Ok(())
}
