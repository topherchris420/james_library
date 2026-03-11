//! Proxy handlers for R.A.I.N. Lab Python bridge.
//!
//! When `[rain_lab] enabled = true`, the gateway forwards meeting
//! requests to the Python bridge server running on `bridge_host:bridge_port`.
//!
//! Routes:
//! - `POST /api/meeting/start`  → proxy to Python `POST /meeting/start`
//! - `POST /api/meeting/stop`   → proxy to Python `POST /meeting/stop`
//! - `GET  /api/meeting/status` → proxy to Python `GET  /meeting/status`

use super::AppState;
use axum::{
    body::Bytes,
    extract::State,
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Json},
};

/// Build the Python bridge base URL from config.
fn bridge_url(state: &AppState) -> String {
    let config = state.config.lock();
    format!(
        "http://{}:{}",
        config.rain_lab.bridge_host, config.rain_lab.bridge_port
    )
}

/// Check that `[rain_lab] enabled = true`; return an error response otherwise.
fn require_enabled(state: &AppState) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    let enabled = state.config.lock().rain_lab.enabled;
    if enabled {
        Ok(())
    } else {
        Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({
                "error": "R.A.I.N. Lab bridge is not enabled. Set [rain_lab] enabled = true in config.toml"
            })),
        ))
    }
}

/// Require bearer-token auth (same as other /api/* routes).
fn require_auth(
    state: &AppState,
    headers: &HeaderMap,
) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    if !state.pairing.require_pairing() {
        return Ok(());
    }
    let token = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|auth| auth.strip_prefix("Bearer "))
        .unwrap_or("");
    if state.pairing.is_authenticated(token) {
        Ok(())
    } else {
        Err((
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({
                "error": "Unauthorized — pair first via POST /pair"
            })),
        ))
    }
}

// ── Handlers ─────────────────────────────────────────────────────

/// `POST /api/meeting/start` — start a new R.A.I.N. Lab meeting.
pub async fn handle_meeting_start(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> impl IntoResponse {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    if let Err(e) = require_enabled(&state) {
        return e.into_response();
    }

    let url = format!("{}/meeting/start", bridge_url(&state));
    proxy_post(&url, &body, &state).await.into_response()
}

/// `POST /api/meeting/stop` — stop the current meeting.
pub async fn handle_meeting_stop(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> impl IntoResponse {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    if let Err(e) = require_enabled(&state) {
        return e.into_response();
    }

    let url = format!("{}/meeting/stop", bridge_url(&state));
    proxy_post(&url, &body, &state).await.into_response()
}

/// `GET /api/meeting/status` — query current meeting state.
pub async fn handle_meeting_status(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> impl IntoResponse {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    if let Err(e) = require_enabled(&state) {
        return e.into_response();
    }

    let url = format!("{}/meeting/status", bridge_url(&state));
    proxy_get(&url, &state).await.into_response()
}

// ── Internal proxy helpers ───────────────────────────────────────

async fn proxy_post(
    url: &str,
    body: &[u8],
    state: &AppState,
) -> (StatusCode, Json<serde_json::Value>) {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .unwrap_or_default();

    match client
        .post(url)
        .header("Content-Type", "application/json")
        .body(body.to_vec())
        .send()
        .await
    {
        Ok(resp) => {
            let status = resp.status();
            let body_text = resp.text().await.unwrap_or_default();
            let json: serde_json::Value =
                serde_json::from_str(&body_text).unwrap_or(serde_json::json!({"raw": body_text}));

            // Forward meeting events to SSE broadcast
            if let Some(meeting_id) = json.get("meeting_id") {
                let _ = state.event_tx.send(serde_json::json!({
                    "type": "rain_lab_meeting",
                    "action": "started",
                    "meeting_id": meeting_id,
                }));
            }

            (
                StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::BAD_GATEWAY),
                Json(json),
            )
        }
        Err(e) => (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({
                "error": format!("Bridge unreachable: {e}"),
                "hint": "Ensure rain_bridge_server.py is running"
            })),
        ),
    }
}

async fn proxy_get(
    url: &str,
    _state: &AppState,
) -> (StatusCode, Json<serde_json::Value>) {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .unwrap_or_default();

    match client.get(url).send().await {
        Ok(resp) => {
            let status = resp.status();
            let body_text = resp.text().await.unwrap_or_default();
            let json: serde_json::Value =
                serde_json::from_str(&body_text).unwrap_or(serde_json::json!({"raw": body_text}));
            (
                StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::BAD_GATEWAY),
                Json(json),
            )
        }
        Err(e) => (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({
                "error": format!("Bridge unreachable: {e}"),
                "hint": "Ensure rain_bridge_server.py is running"
            })),
        ),
    }
}
