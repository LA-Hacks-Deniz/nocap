// Owner: DEVIN — Phase 3 task T3.27
//
// POST /api/traces/:trace_id/replay
//
// Reads the stored trace doc from MongoDB, extracts the original
// `arxiv_id` + `code_str` + `function_name` (and optional `claim`), then
// reuses `verify::spawn_council_run` to fire-and-forget a fresh
// verification. Returns `{"trace_id": "<new-uuid>"}` so the dashboard
// can navigate to the new trace page immediately.
//
// Depends on T3.24 having shipped — without `code_str` persisted in the
// trace doc, replay returns a 422 with a clear error message so the
// dashboard can show "this trace pre-dates code_str persistence and
// can't be replayed automatically".

use std::env;

use axum::{
    extract::Path,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use mongodb::bson::{doc, Document};
use serde::Serialize;
use serde_json::Value;

use crate::routes::verify;

const DB_NAME: &str = "nocap";
const COLLECTION_NAME: &str = "traces";

#[derive(Debug, Serialize)]
pub struct ReplayResp {
    pub trace_id: String,
}

pub async fn replay_trace(Path(trace_id): Path<String>) -> Result<Json<ReplayResp>, ApiError> {
    tracing::info!(trace_id = %trace_id, "replay_trace");

    let coll = mongo_collection().await?;
    let doc = coll
        .find_one(doc! { "trace_id": &trace_id }, None)
        .await
        .map_err(|e| ApiError::internal(format!("mongo find_one: {e}")))?
        .ok_or_else(|| ApiError::not_found("trace not found".to_string()))?;

    // The trace doc is the augmented orchestrator dict — top-level
    // `arxiv_id` / `function_name` / `code_str` per `mongo_log.log_verdict`
    // and orchestrator T3.24. `claim` is a nested dict; for replay we
    // pass `None` so the orchestrator re-extracts a fresh claim from the
    // paper rather than using the prior run's possibly-stale claim text.
    let v: Value = serde_json::to_value(&doc)
        .map_err(|e| ApiError::internal(format!("bson→json: {e}")))?;

    let arxiv_id = v
        .get("arxiv_id")
        .and_then(|x| x.as_str())
        .ok_or_else(|| ApiError::unprocessable("trace doc missing arxiv_id".to_string()))?;
    let code_str = v.get("code_str").and_then(|x| x.as_str()).ok_or_else(|| {
        ApiError::unprocessable(
            "trace doc missing code_str — pre-T3.24 traces can't be replayed".to_string(),
        )
    })?;
    if code_str.is_empty() {
        return Err(ApiError::unprocessable(
            "trace doc has empty code_str".to_string(),
        ));
    }
    let function_name = v.get("function_name").and_then(|x| x.as_str());

    let new_trace_id = verify::spawn_council_run(arxiv_id, code_str, function_name, None)
        .await
        .map_err(|e| ApiError::internal(format!("spawn_council_run: {e}")))?;

    Ok(Json(ReplayResp { trace_id: new_trace_id }))
}

// ---------------------------------------------------------------------------
// Mongo helper (per-request, mirrors traces.rs / slack.rs)
// ---------------------------------------------------------------------------

async fn mongo_collection() -> Result<mongodb::Collection<Document>, ApiError> {
    let uri = env::var("MONGODB_URI")
        .map_err(|_| ApiError::internal("MONGODB_URI not set".to_string()))?;
    let client = mongodb::Client::with_uri_str(&uri)
        .await
        .map_err(|e| ApiError::internal(format!("mongo connect: {e}")))?;
    Ok(client.database(DB_NAME).collection(COLLECTION_NAME))
}

// ---------------------------------------------------------------------------
// Error type — uniform `{"error": "..."}` JSON shape
// ---------------------------------------------------------------------------

pub struct ApiError {
    pub status: StatusCode,
    pub message: String,
}

impl ApiError {
    pub fn internal(message: String) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message,
        }
    }
    pub fn not_found(message: String) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            message,
        }
    }
    pub fn unprocessable(message: String) -> Self {
        Self {
            status: StatusCode::UNPROCESSABLE_ENTITY,
            message,
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        tracing::error!(status = %self.status, message = %self.message, "replay api error");
        (
            self.status,
            Json(serde_json::json!({ "error": self.message })),
        )
            .into_response()
    }
}
