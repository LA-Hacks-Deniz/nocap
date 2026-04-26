// Owner: CLAUDE — Phase 2 task T2.10
//
// POST /slack-event — handles two distinct payloads on the same URL:
//   * Slash command (`/nocap verify-impl <arxiv-id> <code-or-url>`):
//     application/x-www-form-urlencoded with `command`, `text`, `response_url`.
//   * Interactivity (button clicks): application/x-www-form-urlencoded
//     with a single `payload` field whose value is URL-encoded JSON.
//
// Slack requires HTTP 200 within 3 seconds. We verify the signing secret,
// ack with a `:hourglass:` placeholder, and `tokio::spawn` the verify
// flow. The flow:
//
//   1. Resolve `<code-or-url>` to a code body (GitHub blob URL → raw,
//      GitHub PR URL → diff via API, ```fence``` → first block, else
//      treat as inline code).
//   2. POST `/verify-impl` on this same gateway to spawn the council.
//   3. Poll `nocap.traces` by `trace_id` (every 2s, 60s deadline) for
//      the verdict the orchestrator persists via mongo_log.
//   4. Replace the original Slack message via `response_url` with a
//      Block Kit verdict (header + per-evidence sections + buttons).
//
// Interactivity handler dispatches on `action_id`:
//   * `view_trace` — replies with `https://nocap.wiki/trace/<id>` (T3 frontend).
//   * `approve_anyway` — logs and ephemerally acks the click.

use std::collections::HashMap;
use std::env;
use std::time::{Duration, Instant};

use axum::{
    body::Bytes,
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use hmac::{Hmac, Mac};
use mongodb::bson::{doc, Document};
use serde_json::{json, Value};
use sha2::Sha256;

const TIMESTAMP_TOLERANCE_S: i64 = 60 * 5;
const POLL_INTERVAL: Duration = Duration::from_secs(2);
const POLL_DEADLINE: Duration = Duration::from_secs(150);

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

pub async fn slack_event(headers: HeaderMap, body: Bytes) -> axum::response::Response {
    let signing_secret = match env::var("SLACK_SIGNING_SECRET") {
        Ok(v) => v,
        Err(_) => {
            tracing::error!("SLACK_SIGNING_SECRET not set");
            return ephemeral("⚠️ server misconfigured: SLACK_SIGNING_SECRET not set");
        }
    };

    if let Err(why) = verify_slack_signature(&headers, &body, &signing_secret) {
        tracing::warn!(why = %why, "slack signature verification failed");
        return (StatusCode::UNAUTHORIZED, "invalid signature").into_response();
    }

    let parsed: HashMap<String, String> = match serde_urlencoded::from_bytes(&body) {
        Ok(p) => p,
        Err(e) => {
            tracing::error!(error = %e, "could not urldecode slack body");
            return (StatusCode::BAD_REQUEST, "bad form body").into_response();
        }
    };

    if let Some(payload_json) = parsed.get("payload") {
        return handle_interactivity(payload_json).await;
    }
    if parsed.get("command").is_some() {
        return handle_slash_command(parsed).await;
    }

    tracing::warn!(?parsed, "unknown slack body");
    ephemeral("⚠️ unknown slack event")
}

// ---------------------------------------------------------------------------
// Signature verification
// ---------------------------------------------------------------------------

fn verify_slack_signature(headers: &HeaderMap, body: &[u8], secret: &str) -> Result<(), String> {
    let sig = headers
        .get("X-Slack-Signature")
        .or_else(|| headers.get("x-slack-signature"))
        .and_then(|v| v.to_str().ok())
        .ok_or("missing X-Slack-Signature")?;
    let ts_str = headers
        .get("X-Slack-Request-Timestamp")
        .or_else(|| headers.get("x-slack-request-timestamp"))
        .and_then(|v| v.to_str().ok())
        .ok_or("missing X-Slack-Request-Timestamp")?;
    let ts: i64 = ts_str.parse().map_err(|_| "bad timestamp")?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| "system clock before epoch")?
        .as_secs() as i64;
    if (now - ts).abs() > TIMESTAMP_TOLERANCE_S {
        return Err(format!("timestamp out of window (now={now}, ts={ts})"));
    }

    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(secret.as_bytes())
        .map_err(|e| format!("hmac init: {e}"))?;
    mac.update(b"v0:");
    mac.update(ts_str.as_bytes());
    mac.update(b":");
    mac.update(body);
    let expected = format!("v0={}", hex::encode(mac.finalize().into_bytes()));

    if !constant_time_eq(sig.as_bytes(), expected.as_bytes()) {
        return Err("signature mismatch".into());
    }
    Ok(())
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff: u8 = 0;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

// ---------------------------------------------------------------------------
// Slash command
// ---------------------------------------------------------------------------

async fn handle_slash_command(fields: HashMap<String, String>) -> axum::response::Response {
    let command = fields.get("command").cloned().unwrap_or_default();
    if command != "/nocap" {
        return ephemeral(&format!("⚠️ unknown command: {command}"));
    }

    let text = fields.get("text").cloned().unwrap_or_default();
    let response_url = fields.get("response_url").cloned();

    let mut parts = text.trim().splitn(3, char::is_whitespace);
    let subcommand = parts.next().unwrap_or("");
    let arxiv_id = parts.next().unwrap_or("").trim().to_string();
    let rest = parts.next().unwrap_or("").trim().to_string();

    if subcommand != "verify-impl" || arxiv_id.is_empty() || rest.is_empty() {
        return ephemeral(
            "Usage: `/nocap verify-impl <arxiv-id> <code-or-pr-or-blob-url>`\n\
             Example: `/nocap verify-impl 1412.6980 https://github.com/me/nocap/blob/main/file.py`",
        );
    }

    tokio::spawn({
        let arxiv = arxiv_id.clone();
        async move {
            if let Err(e) = run_verify_flow(arxiv, rest, response_url).await {
                tracing::error!(error = %e, "slack verify flow failed");
            }
        }
    });

    Json(json!({
        "response_type": "in_channel",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": format!("🔍 Verifying paper *{arxiv_id}*… (≈90s)")
                }
            }
        ]
    }))
    .into_response()
}

// ---------------------------------------------------------------------------
// Verify flow (runs in background, posts result via response_url)
// ---------------------------------------------------------------------------

async fn run_verify_flow(
    arxiv_id: String,
    code_text: String,
    response_url: Option<String>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let code = resolve_code(&code_text).await?;

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()?;
    let resp: VerifyImplResp = client
        .post("http://localhost:8787/verify-impl")
        .json(&json!({
            "paper_arxiv_id": arxiv_id,
            "code": code,
        }))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    let trace_id = resp.trace_id;
    tracing::info!(trace_id = %trace_id, "slack: verify-impl spawned");

    let verdict = match poll_mongo_for_trace(&trace_id).await {
        Ok(v) => v,
        Err(e) => {
            tracing::error!(trace_id = %trace_id, error = %e, "poll deadline exceeded");
            if let Some(url) = response_url {
                let _ = post_response(
                    &url,
                    json!({
                        "replace_original": true,
                        "response_type": "in_channel",
                        "text": format!("⌛ Verification timed out after 60s (trace `{trace_id}`)."),
                    }),
                )
                .await;
            }
            return Err(e.into());
        }
    };

    let blocks = render_verdict_blocks(&trace_id, &verdict);
    if let Some(url) = response_url {
        post_response(
            &url,
            json!({
                "replace_original": true,
                "response_type": "in_channel",
                "blocks": blocks,
                "text": "No Cap verdict",
            }),
        )
        .await?;
    }
    Ok(())
}

#[derive(serde::Deserialize)]
struct VerifyImplResp {
    trace_id: String,
}

async fn post_response(
    url: &str,
    body: Value,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let resp = reqwest::Client::new().post(url).json(&body).send().await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let txt = resp.text().await.unwrap_or_default();
        return Err(format!("slack response_url {status}: {txt}").into());
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Code resolution: blob URL / PR URL / code fence / inline
// ---------------------------------------------------------------------------

async fn resolve_code(text: &str) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    // Slack wraps URLs as <https://…|label> or <https://…> — strip that.
    let stripped = strip_slack_link(text.trim());

    if let Some(raw) = github_blob_to_raw(&stripped) {
        tracing::info!(url = %raw, "fetching GitHub blob as raw");
        let body = http_get(&raw, /*github_api=*/ false, None).await?;
        return Ok(body);
    }

    if let Some((owner, repo, num)) = parse_github_pr(&stripped) {
        let url = format!("https://api.github.com/repos/{owner}/{repo}/pulls/{num}");
        tracing::info!(url = %url, "fetching GitHub PR diff");
        let token = env::var("GITHUB_TOKEN").ok();
        let body = http_get(&url, /*github_api=*/ true, token.as_deref()).await?;
        return Ok(body);
    }

    if stripped.contains("```") {
        if let Some(code) = extract_code_fence(&stripped) {
            return Ok(code);
        }
    }

    Ok(stripped)
}

fn strip_slack_link(text: &str) -> String {
    let trimmed = text.trim();
    if trimmed.starts_with('<') && trimmed.ends_with('>') {
        let inner = &trimmed[1..trimmed.len() - 1];
        if let Some(idx) = inner.find('|') {
            return inner[..idx].to_string();
        }
        return inner.to_string();
    }
    trimmed.to_string()
}

fn github_blob_to_raw(url: &str) -> Option<String> {
    // https://github.com/<owner>/<repo>/blob/<ref>/<path>
    let prefix = "https://github.com/";
    if !url.starts_with(prefix) {
        return None;
    }
    let rest = &url[prefix.len()..];
    let mut parts = rest.splitn(5, '/');
    let owner = parts.next()?;
    let repo = parts.next()?;
    let blob = parts.next()?;
    let git_ref = parts.next()?;
    let path = parts.next()?;
    if blob != "blob" {
        return None;
    }
    Some(format!(
        "https://raw.githubusercontent.com/{owner}/{repo}/{git_ref}/{path}"
    ))
}

fn parse_github_pr(url: &str) -> Option<(String, String, String)> {
    // https://github.com/<owner>/<repo>/pull/<n>
    let prefix = "https://github.com/";
    if !url.starts_with(prefix) {
        return None;
    }
    let rest = &url[prefix.len()..];
    let mut parts = rest.split('/');
    let owner = parts.next()?.to_string();
    let repo = parts.next()?.to_string();
    let pull = parts.next()?;
    let num = parts.next()?.to_string();
    if pull != "pull" {
        return None;
    }
    Some((owner, repo, num))
}

fn extract_code_fence(text: &str) -> Option<String> {
    let opener = text.find("```")?;
    let after = &text[opener + 3..];
    // Skip optional language tag on the same line as the opener.
    let body_start = after.find('\n').map(|i| i + 1).unwrap_or(0);
    let body = &after[body_start..];
    let closer = body.find("```")?;
    Some(body[..closer].to_string())
}

async fn http_get(
    url: &str,
    github_api: bool,
    token: Option<&str>,
) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    let mut req = reqwest::Client::new()
        .get(url)
        .header("User-Agent", "nocap-gateway/0.1");
    if github_api {
        req = req.header("Accept", "application/vnd.github.v3.diff");
    }
    if let Some(t) = token {
        req = req.header("Authorization", format!("Bearer {t}"));
    }
    let resp = req.send().await?.error_for_status()?;
    Ok(resp.text().await?)
}

// ---------------------------------------------------------------------------
// Mongo polling
// ---------------------------------------------------------------------------

async fn poll_mongo_for_trace(
    trace_id: &str,
) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
    let uri = env::var("MONGODB_URI")?;
    let client = mongodb::Client::with_uri_str(&uri).await?;
    let coll: mongodb::Collection<Document> =
        client.database("nocap").collection("traces");

    let deadline = Instant::now() + POLL_DEADLINE;
    loop {
        if let Some(d) = coll.find_one(doc! { "trace_id": trace_id }, None).await? {
            let mut v = serde_json::to_value(&d)?;
            // BSON ObjectId serializes as {"$oid": "..."} — stringify for caller.
            if let Some(obj) = v.as_object_mut() {
                if let Some(oid) = obj.get("_id").and_then(|x| x.get("$oid")).cloned() {
                    obj.insert("_id".to_string(), oid);
                }
            }
            return Ok(v);
        }
        if Instant::now() >= deadline {
            return Err(format!("no trace doc for {trace_id} within 60s").into());
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

// ---------------------------------------------------------------------------
// Verdict rendering — Block Kit
// ---------------------------------------------------------------------------

fn render_verdict_blocks(trace_id: &str, verdict: &Value) -> Value {
    let kind = verdict
        .get("verdict")
        .and_then(|v| v.as_str())
        .unwrap_or("inconclusive");
    let confidence = verdict
        .get("confidence")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    let arxiv_id = verdict
        .get("arxiv_id")
        .and_then(|v| v.as_str())
        .unwrap_or("?");
    let function_name = verdict
        .get("function_name")
        .and_then(|v| v.as_str())
        .unwrap_or("?");
    let claim = verdict.get("claim");
    let section = claim
        .and_then(|c| c.get("paper_section"))
        .and_then(|s| s.as_str())
        .unwrap_or("?");

    let (icon, headline) = match kind {
        "pass" => ("🟢", "No Cap — Implementation matches paper"),
        "anomaly" => ("🔴", "No Cap — Anomaly detected"),
        _ => ("🟡", "No Cap — Inconclusive"),
    };

    let mut blocks: Vec<Value> = vec![
        json!({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": format!("{icon} {headline}")
            }
        }),
        json!({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": format!("*Confidence:*\n{:.2}", confidence)},
                {"type": "mrkdwn", "text": format!("*Paper:*\narxiv:{arxiv_id} §{section}")},
                {"type": "mrkdwn", "text": format!("*Function:*\n`{function_name}`")},
                {"type": "mrkdwn", "text": format!("*Trace:*\n`{trace_id}`")}
            ]
        }),
    ];

    if kind == "anomaly" {
        if let Some(evs) = verdict.get("evidences").and_then(|v| v.as_array()) {
            for ev in evs {
                if ev.get("equivalent") != Some(&Value::Bool(false)) {
                    continue;
                }
                let kind_str = ev.get("kind").and_then(|v| v.as_str()).unwrap_or("?");
                let target = ev.get("target_var").and_then(|v| v.as_str()).unwrap_or("?");
                let residual = ev
                    .get("residual")
                    .and_then(|v| v.as_str())
                    .unwrap_or("(no residual)");
                let critic = ev
                    .get("critic_feedback")
                    .and_then(|v| v.as_str())
                    .map(|s| {
                        s.split_terminator(['.', '!', '?'])
                            .next()
                            .unwrap_or(s)
                            .trim()
                            .to_string()
                    });
                let mut text = format!(
                    "*[{kind_str}]* `{target}` mismatch\n*Residual:* `{residual}`"
                );
                if let Some(c) = critic {
                    if !c.is_empty() {
                        text.push_str(&format!("\n*Critic:* {c}"));
                    }
                }
                blocks.push(json!({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text}
                }));
            }
        }
    }

    if kind == "inconclusive" {
        if let Some(summary) = verdict.get("evidence_summary").and_then(|v| v.as_str()) {
            blocks.push(json!({
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary}
            }));
        }
    }

    // T3.33: "View Issue" is a direct external link to the dashboard
    // trace detail page. With `url` set, Slack opens the URL in a new
    // tab and does NOT call back to /slack-event — the obsolete
    // "view_trace" action_id handler was removed from
    // handle_interactivity below.
    blocks.push(json!({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View Issue"},
                "action_id": "view_issue",
                "url": format!("https://nocap.wiki/trace/{}", trace_id),
                "value": trace_id
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve anyway"},
                "action_id": "approve_anyway",
                "value": trace_id,
                "style": "danger"
            }
        ]
    }));

    Value::Array(blocks)
}

// ---------------------------------------------------------------------------
// Interactivity (button clicks)
// ---------------------------------------------------------------------------

async fn handle_interactivity(payload_json: &str) -> axum::response::Response {
    let payload: Value = match serde_json::from_str(payload_json) {
        Ok(v) => v,
        Err(e) => {
            tracing::error!(error = %e, "could not parse interactivity payload");
            return (StatusCode::BAD_REQUEST, "bad payload").into_response();
        }
    };

    let action = payload.pointer("/actions/0");
    let action_id = action
        .and_then(|a| a.get("action_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let trace_id = action
        .and_then(|a| a.get("value"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let user = payload
        .pointer("/user/username")
        .and_then(|v| v.as_str())
        .unwrap_or("?");
    let response_url = payload
        .get("response_url")
        .and_then(|v| v.as_str())
        .map(String::from);

    // T3.33 removed the "view_trace" action_id handler — the "View
    // Issue" button now ships with a `url` field so Slack opens it as
    // an external link and never round-trips here.
    let text = match action_id {
        "approve_anyway" => {
            tracing::warn!(user = %user, trace_id = %trace_id, "approve_anyway clicked");
            format!("✅ {user} approved trace `{trace_id}` anyway. Logged.")
        }
        other => format!("Unknown action: {other}"),
    };

    if let Some(url) = response_url {
        let _ = post_response(
            &url,
            json!({
                "response_type": "ephemeral",
                "replace_original": false,
                "text": text,
            }),
        )
        .await;
    }

    StatusCode::OK.into_response()
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn ephemeral(msg: &str) -> axum::response::Response {
    Json(json!({"response_type": "ephemeral", "text": msg})).into_response()
}
