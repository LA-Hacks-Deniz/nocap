// Owner: DEVIN — Phase 3 task T3.23
//
// Public read API consumed by the Vercel-hosted dashboard at
// `nocap.wiki/dashboard` and `nocap.wiki/trace/[id]`. Exposes:
//
//   GET /api/traces?limit=N&offset=N    → paginated trace summaries
//   GET /api/traces/:trace_id           → full trace doc
//   GET /api/papers/:arxiv_id/pdf       → arXiv PDF proxy (CORS-safe)
//
// All errors render as `{"error": "..."}` JSON so the dashboard can show a
// uniform toast. Mongo client is created per-request to mirror
// `slack.rs::poll_mongo_for_trace` — connection churn is fine at hackathon
// traffic volumes; switch to a `OnceCell<Client>` if it ever shows up in a
// flame graph.

use std::env;
use std::time::Duration;

use axum::{
    body::Body,
    extract::{Path, Query},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use mongodb::{
    bson::{doc, Document},
    options::FindOptions,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

const DB_NAME: &str = "nocap";
const COLLECTION_NAME: &str = "traces";

const DEFAULT_LIMIT: i64 = 50;
const MAX_LIMIT: i64 = 200;

const ARXIV_PDF_TIMEOUT: Duration = Duration::from_secs(10);
const ARXIV_USER_AGENT: &str = "nocap-gateway/0.1 (+https://nocap.wiki)";

// ---------------------------------------------------------------------------
// GET /api/traces — paginated list of summaries
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct ListQuery {
    #[serde(default)]
    pub limit: Option<i64>,
    #[serde(default)]
    pub offset: Option<i64>,
}

#[derive(Debug, Serialize)]
pub struct TraceSummary {
    pub trace_id: Option<String>,
    pub arxiv_id: Option<String>,
    pub function_name: Option<String>,
    pub verdict: Option<String>,
    pub confidence: Option<f64>,
    pub paper_section: Option<String>,
    pub created_at: Option<String>,
}

pub async fn list_traces(Query(q): Query<ListQuery>) -> Result<Json<Vec<TraceSummary>>, ApiError> {
    let limit = q.limit.unwrap_or(DEFAULT_LIMIT).clamp(1, MAX_LIMIT);
    let offset = q.offset.unwrap_or(0).max(0);

    tracing::info!(limit, offset, "list_traces");

    let coll = mongo_collection().await?;
    let opts = FindOptions::builder()
        .sort(doc! { "created_at": -1 })
        .skip(Some(offset as u64))
        .limit(Some(limit))
        .projection(doc! {
            "trace_id": 1,
            "arxiv_id": 1,
            "function_name": 1,
            "verdict": 1,
            "confidence": 1,
            "created_at": 1,
            "claim.paper_section": 1,
        })
        .build();

    let mut cursor = coll
        .find(None, opts)
        .await
        .map_err(|e| ApiError::internal(format!("mongo find: {e}")))?;

    let mut out: Vec<TraceSummary> = Vec::new();
    while cursor
        .advance()
        .await
        .map_err(|e| ApiError::internal(format!("mongo cursor advance: {e}")))?
    {
        let d: Document = cursor
            .deserialize_current()
            .map_err(|e| ApiError::internal(format!("mongo deserialize: {e}")))?;
        out.push(summary_from_doc(&d));
    }
    Ok(Json(out))
}

fn summary_from_doc(d: &Document) -> TraceSummary {
    TraceSummary {
        trace_id: d.get_str("trace_id").ok().map(str::to_string),
        arxiv_id: d.get_str("arxiv_id").ok().map(str::to_string),
        function_name: d.get_str("function_name").ok().map(str::to_string),
        verdict: d.get_str("verdict").ok().map(str::to_string),
        confidence: d.get_f64("confidence").ok().or_else(|| {
            // Mongo sometimes stores numerics as i32/i64 if a doc was hand-edited.
            d.get_i64("confidence").ok().map(|i| i as f64)
        }),
        paper_section: d
            .get_document("claim")
            .ok()
            .and_then(|c| c.get_str("paper_section").ok())
            .map(str::to_string),
        created_at: d.get_str("created_at").ok().map(str::to_string),
    }
}

// ---------------------------------------------------------------------------
// GET /api/traces/:trace_id — full doc
// ---------------------------------------------------------------------------

pub async fn get_trace(Path(trace_id): Path<String>) -> Result<Json<Value>, ApiError> {
    tracing::info!(trace_id = %trace_id, "get_trace");

    let coll = mongo_collection().await?;
    let doc = coll
        .find_one(doc! { "trace_id": &trace_id }, None)
        .await
        .map_err(|e| ApiError::internal(format!("mongo find_one: {e}")))?
        .ok_or_else(|| ApiError::not_found("trace not found".to_string()))?;

    let mut v = serde_json::to_value(&doc)
        .map_err(|e| ApiError::internal(format!("bson→json: {e}")))?;

    // BSON ObjectId serialises as `{"$oid": "..."}`; flatten to plain string
    // so the dashboard can `?.copy()` it without poking at $oid.
    if let Some(obj) = v.as_object_mut() {
        if let Some(oid) = obj.get("_id").and_then(|x| x.get("$oid")).cloned() {
            obj.insert("_id".to_string(), oid);
        }
    }

    Ok(Json(v))
}

// ---------------------------------------------------------------------------
// GET /api/papers/:arxiv_id/pdf — arXiv proxy
// ---------------------------------------------------------------------------

pub async fn get_paper_pdf(Path(arxiv_id): Path<String>) -> Result<Response, ApiError> {
    if arxiv_id.is_empty() || arxiv_id.contains('/') || arxiv_id.contains("..") {
        return Err(ApiError::bad_request("invalid arxiv_id".to_string()));
    }

    let url = format!("https://arxiv.org/pdf/{arxiv_id}.pdf");
    tracing::info!(%url, "get_paper_pdf");

    let client = reqwest::Client::builder()
        .timeout(ARXIV_PDF_TIMEOUT)
        .user_agent(ARXIV_USER_AGENT)
        .build()
        .map_err(|e| ApiError::internal(format!("reqwest build: {e}")))?;

    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| ApiError::internal(format!("arxiv fetch: {e}")))?;

    if !resp.status().is_success() {
        let status = resp.status();
        return Err(ApiError {
            status: StatusCode::NOT_FOUND,
            message: format!("arxiv returned {status} for {url}"),
        });
    }

    let bytes = resp
        .bytes()
        .await
        .map_err(|e| ApiError::internal(format!("read arxiv body: {e}")))?;

    Ok((
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "application/pdf"),
            (header::CACHE_CONTROL, "public, max-age=3600"),
        ],
        Body::from(bytes),
    )
        .into_response())
}

// ---------------------------------------------------------------------------
// Mongo helper
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
    pub fn bad_request(message: String) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message,
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        tracing::error!(status = %self.status, message = %self.message, "traces api error");
        (
            self.status,
            Json(serde_json::json!({ "error": self.message })),
        )
            .into_response()
    }
}
