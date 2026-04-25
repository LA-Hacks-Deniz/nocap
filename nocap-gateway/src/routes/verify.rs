// Owner: CLAUDE — Phase 2 task T2.9 (Phase 3 T3.27 extracts spawn_council_run)
//
// POST /verify-impl — accepts JSON {paper_arxiv_id, code, claim?,
// function_name?}, drops the code into /tmp/nocap-runs/<trace_id>.py,
// fire-and-forget spawns the council CLI, and returns {trace_id} so the
// caller can subscribe to streamed events / poll Mongo for the final
// verdict (orchestrator persists via mongo_log when it finishes).
//
// T3.27 introduced `spawn_council_run`, a `pub` helper that the new
// `/api/traces/:id/replay` endpoint reuses without re-implementing the
// /tmp scratch + uv-run plumbing.
//
// Council location is read from NOCAP_COUNCIL_DIR (default "nocap-council"
// relative to gateway cwd). Run the gateway from the repo root, or set
// the env var to an absolute path.

use std::path::PathBuf;
use std::process::Stdio;

use axum::{http::StatusCode, response::IntoResponse, Json};
use serde::{Deserialize, Serialize};
use tokio::process::Command;
use uuid::Uuid;

const RUNS_DIR: &str = "/tmp/nocap-runs";
const DEFAULT_COUNCIL_DIR: &str = "nocap-council";

#[derive(Debug, Deserialize)]
pub struct VerifyReq {
    pub paper_arxiv_id: String,
    pub code: String,
    #[serde(default)]
    pub claim: Option<String>,
    #[serde(default)]
    pub function_name: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct VerifyResp {
    pub trace_id: String,
}

/// Drop `code` into `/tmp/nocap-runs/<trace_id>.py`, fire-and-forget
/// spawn the council subprocess with a fresh `NOCAP_TRACE_ID`, and
/// return the generated trace_id. Used by both `/verify-impl` (T2.9)
/// and `/api/traces/:id/replay` (T3.27) so the spawn plumbing stays in
/// one place.
pub async fn spawn_council_run(
    paper_arxiv_id: &str,
    code: &str,
    function_name: Option<&str>,
    claim: Option<&str>,
) -> anyhow::Result<String> {
    let trace_id = Uuid::new_v4().to_string();

    let runs_dir = PathBuf::from(RUNS_DIR);
    tokio::fs::create_dir_all(&runs_dir).await?;

    let code_path = runs_dir.join(format!("{trace_id}.py"));
    tokio::fs::write(&code_path, code).await?;

    let council_dir = std::env::var("NOCAP_COUNCIL_DIR")
        .unwrap_or_else(|_| DEFAULT_COUNCIL_DIR.to_string());
    let code_path_str = code_path
        .to_str()
        .ok_or_else(|| anyhow::anyhow!("non-utf8 code path: {}", code_path.display()))?
        .to_string();

    tracing::info!(
        trace_id = %trace_id,
        paper = %paper_arxiv_id,
        code_path = %code_path_str,
        function_name = ?function_name,
        has_claim = claim.is_some(),
        "spawning council verify"
    );

    let mut cmd = Command::new("uv");
    cmd.args([
        "run",
        "--directory",
        &council_dir,
        "nocap",
        "verify-impl",
        paper_arxiv_id,
        &code_path_str,
    ]);
    if let Some(c) = claim {
        cmd.args(["--claim", c]);
    }
    if let Some(fn_name) = function_name {
        cmd.args(["--function", fn_name]);
    }
    // Thread the gateway-generated trace_id through to the orchestrator
    // so the Mongo doc carries it as a queryable field (slack handler
    // polls by trace_id).
    cmd.env("NOCAP_TRACE_ID", &trace_id);
    // Detach stdio — orchestrator persists its verdict to Mongo, no need
    // to pipe stdout. Letting it inherit would tie the child to the gateway
    // terminal and break when run as a daemon.
    cmd.stdout(Stdio::null())
        .stderr(Stdio::null())
        .stdin(Stdio::null());

    let trace_id_log = trace_id.clone();
    tokio::spawn(async move {
        match cmd.spawn() {
            Ok(mut child) => match child.wait().await {
                Ok(status) => {
                    tracing::info!(trace_id = %trace_id_log, code = ?status.code(), "verify finished")
                }
                Err(e) => tracing::error!(trace_id = %trace_id_log, error = %e, "child wait failed"),
            },
            Err(e) => tracing::error!(trace_id = %trace_id_log, error = %e, "spawn failed"),
        }
    });

    Ok(trace_id)
}

pub async fn verify_impl(Json(req): Json<VerifyReq>) -> Result<Json<VerifyResp>, ApiError> {
    let trace_id = spawn_council_run(
        &req.paper_arxiv_id,
        &req.code,
        req.function_name.as_deref(),
        req.claim.as_deref(),
    )
    .await
    .map_err(|e| ApiError::internal(format!("spawn_council_run: {e}")))?;
    Ok(Json(VerifyResp { trace_id }))
}

pub struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    fn internal(message: String) -> Self {
        Self { status: StatusCode::INTERNAL_SERVER_ERROR, message }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> axum::response::Response {
        tracing::error!(status = %self.status, message = %self.message, "verify error");
        (self.status, Json(serde_json::json!({ "error": self.message }))).into_response()
    }
}
