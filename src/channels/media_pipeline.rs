//! Automatic media understanding pipeline for inbound channel messages.
//!
//! Pre-processes audio, image, and video attachments before they reach the agent,
//! enriching message text with human-readable annotations. Opt-in via
//! `[media_pipeline] enabled = true` in config.

use serde::{Deserialize, Serialize};

/// Classification of a media attachment by content type.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum MediaKind {
    Audio,
    Image,
    Video,
    Unknown,
}

impl MediaKind {
    /// Detect media kind from MIME type (priority) or file extension fallback.
    pub fn detect(mime_type: Option<&str>, file_name: &str) -> Self {
        if let Some(mime) = mime_type {
            if mime.starts_with("audio/") {
                return Self::Audio;
            }
            if mime.starts_with("image/") {
                return Self::Image;
            }
            if mime.starts_with("video/") {
                return Self::Video;
            }
        }
        // Extension fallback
        let lower = file_name.to_lowercase();
        if lower.ends_with(".mp3")
            || lower.ends_with(".wav")
            || lower.ends_with(".ogg")
            || lower.ends_with(".flac")
            || lower.ends_with(".m4a")
            || lower.ends_with(".opus")
        {
            return Self::Audio;
        }
        if lower.ends_with(".jpg")
            || lower.ends_with(".jpeg")
            || lower.ends_with(".png")
            || lower.ends_with(".gif")
            || lower.ends_with(".webp")
            || lower.ends_with(".bmp")
        {
            return Self::Image;
        }
        if lower.ends_with(".mp4")
            || lower.ends_with(".mov")
            || lower.ends_with(".avi")
            || lower.ends_with(".webm")
            || lower.ends_with(".mkv")
        {
            return Self::Video;
        }
        Self::Unknown
    }
}

/// A single media attachment on a channel message.
#[derive(Debug, Clone)]
pub struct MediaAttachment {
    /// Original filename of the attachment.
    pub file_name: String,
    /// Raw bytes of the attachment content.
    pub data: Vec<u8>,
    /// Optional MIME type (e.g. `image/png`, `audio/ogg`).
    pub mime_type: Option<String>,
}

impl MediaAttachment {
    /// Create a new media attachment.
    pub fn new(file_name: impl Into<String>, data: Vec<u8>) -> Self {
        Self {
            file_name: file_name.into(),
            data,
            mime_type: None,
        }
    }

    /// Set the MIME type.
    pub fn with_mime(mut self, mime: impl Into<String>) -> Self {
        self.mime_type = Some(mime.into());
        self
    }

    /// Detect the media kind of this attachment.
    pub fn kind(&self) -> MediaKind {
        MediaKind::detect(self.mime_type.as_deref(), &self.file_name)
    }
}

/// Media pipeline configuration.
#[allow(clippy::struct_excessive_bools)]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MediaPipelineConfig {
    /// Whether the media pipeline is enabled.
    #[serde(default)]
    pub enabled: bool,
    /// Whether to transcribe audio attachments.
    #[serde(default = "default_true")]
    pub transcribe_audio: bool,
    /// Whether to describe images (when vision model available).
    #[serde(default = "default_true")]
    pub describe_images: bool,
    /// Whether to summarize video attachments.
    #[serde(default)]
    pub summarize_video: bool,
}

fn default_true() -> bool {
    true
}

impl Default for MediaPipelineConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            transcribe_audio: true,
            describe_images: true,
            summarize_video: false,
        }
    }
}

/// Enrich a message with media annotations.
///
/// Returns the original text prepended with annotations for each attachment.
pub fn enrich_message(
    text: &str,
    attachments: &[MediaAttachment],
    vision_available: bool,
) -> String {
    if attachments.is_empty() {
        return text.to_string();
    }

    let mut annotations = Vec::new();
    for attachment in attachments {
        let annotation = match attachment.kind() {
            MediaKind::Audio => format!("[Audio: {} attached]", attachment.file_name),
            MediaKind::Image => {
                if vision_available {
                    format!(
                        "[Image: {} attached, will be processed by vision model]",
                        attachment.file_name
                    )
                } else {
                    format!("[Image: {} attached]", attachment.file_name)
                }
            }
            MediaKind::Video => format!("[Video: {} attached]", attachment.file_name),
            MediaKind::Unknown => format!("[Attachment: {} attached]", attachment.file_name),
        };
        annotations.push(annotation);
    }

    if text.is_empty() {
        annotations.join("\n")
    } else {
        format!("{}\n{}", annotations.join("\n"), text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn media_kind_detect_from_mime() {
        assert_eq!(
            MediaKind::detect(Some("audio/ogg"), "file"),
            MediaKind::Audio
        );
        assert_eq!(
            MediaKind::detect(Some("image/png"), "file"),
            MediaKind::Image
        );
        assert_eq!(
            MediaKind::detect(Some("video/mp4"), "file"),
            MediaKind::Video
        );
        assert_eq!(
            MediaKind::detect(Some("text/plain"), "file"),
            MediaKind::Unknown
        );
    }

    #[test]
    fn media_kind_detect_from_extension() {
        assert_eq!(MediaKind::detect(None, "song.mp3"), MediaKind::Audio);
        assert_eq!(MediaKind::detect(None, "photo.jpg"), MediaKind::Image);
        assert_eq!(MediaKind::detect(None, "clip.mp4"), MediaKind::Video);
        assert_eq!(MediaKind::detect(None, "data.bin"), MediaKind::Unknown);
    }

    #[test]
    fn enrich_message_with_image_and_vision() {
        let attachments = vec![MediaAttachment::new("photo.png", vec![0u8; 4])];
        let result = enrich_message("Hello", &attachments, true);
        assert!(result.contains("will be processed by vision model"));
        assert!(result.contains("Hello"));
    }

    #[test]
    fn enrich_message_empty_attachments() {
        let result = enrich_message("Hello", &[], false);
        assert_eq!(result, "Hello");
    }
}
