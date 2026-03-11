//! Static file serving for the embedded web dashboard.
//!
//! Uses `rust-embed` to bundle the `web/dist/` directory into the binary at compile time.

use axum::{
    body::Body,
    http::{header, StatusCode, Uri},
    response::{IntoResponse, Response},
};
use rust_embed::Embed;

#[derive(Embed)]
#[folder = "web/dist/"]
struct WebAssets;

const CACHE_IMMUTABLE: &str = "public, max-age=31536000, immutable";
const CACHE_NO_STORE: &str = "no-cache";

fn content_type_for(path: &str) -> &'static str {
    mime_guess::from_path(path)
        .first_raw()
        .unwrap_or("application/octet-stream")
}

fn is_safe_asset_path(path: &str) -> bool {
    !path.is_empty()
        && !path.contains('\\')
        && path
            .split('/')
            .all(|segment| !segment.is_empty() && segment != "." && segment != "..")
}

/// Serve static files from `/_app/*` path
pub async fn handle_static(uri: Uri) -> Response {
    let path = uri
        .path()
        .strip_prefix("/_app/")
        .unwrap_or(uri.path())
        .trim_start_matches('/');

    if !is_safe_asset_path(path) {
        return (StatusCode::NOT_FOUND, "Not found").into_response();
    }

    serve_embedded_file(path)
}

/// SPA fallback: serve index.html for any non-API, non-static GET request
pub async fn handle_spa_fallback() -> impl IntoResponse {
    serve_embedded_file("index.html")
}

fn serve_embedded_file(path: &str) -> Response {
    match WebAssets::get(path) {
        Some(content) => {
            let cache_control = if path.contains("assets/") {
                CACHE_IMMUTABLE
            } else {
                CACHE_NO_STORE
            };
            let body = match content.data {
                std::borrow::Cow::Borrowed(bytes) => Body::from(bytes),
                std::borrow::Cow::Owned(bytes) => Body::from(bytes),
            };

            (
                StatusCode::OK,
                [
                    (header::CONTENT_TYPE, content_type_for(path)),
                    (header::CACHE_CONTROL, cache_control),
                ],
                body,
            )
                .into_response()
        }
        None => (StatusCode::NOT_FOUND, "Not found").into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::is_safe_asset_path;

    #[test]
    fn safe_asset_paths_are_accepted() {
        assert!(is_safe_asset_path("assets/app.js"));
        assert!(is_safe_asset_path("assets/chunks/main.css"));
    }

    #[test]
    fn unsafe_asset_paths_are_rejected() {
        assert!(!is_safe_asset_path(""));
        assert!(!is_safe_asset_path("../secret.txt"));
        assert!(!is_safe_asset_path("assets/../secret.txt"));
        assert!(!is_safe_asset_path("assets\\.\\app.js"));
    }
}
