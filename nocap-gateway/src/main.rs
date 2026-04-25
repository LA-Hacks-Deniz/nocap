// Owner: CLAUDE — Phase 2 task T2.8 (T2.9 wires /verify-impl)
// Phase 3 T3.23 mounts /api/traces, /api/traces/:id, /api/papers/:arxiv_id/pdf
// + permissive CORS so the Vercel-hosted dashboard can read from a
// different origin (`https://nocap.wiki` → `https://api.nocap.wiki`).
//
// Axum perimeter. Routes live under `routes/`.

mod routes;

use axum::{
    routing::{get, post},
    Router,
};
use tower_http::cors::CorsLayer;
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
        .route("/slack-event", post(routes::slack::slack_event))
        .route("/api/traces", get(routes::traces::list_traces))
        .route("/api/traces/:trace_id", get(routes::traces::get_trace))
        .route("/api/papers/:arxiv_id/pdf", get(routes::traces::get_paper_pdf))
        // Permissive CORS for the hackathon — Vercel-hosted dashboard at
        // nocap.wiki calls api.nocap.wiki cross-origin. Tighten to
        // `Access-Control-Allow-Origin: https://nocap.wiki` post-deploy.
        .layer(CorsLayer::permissive());

    let listener = tokio::net::TcpListener::bind(BIND_ADDR).await?;
    tracing::info!(addr = %BIND_ADDR, "nocap-gateway listening");
    axum::serve(listener, app).await?;
    Ok(())
}
