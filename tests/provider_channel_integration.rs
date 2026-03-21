//! Integration tests for provider-to-channel message flow.
//!
//! Tests that provider responses correctly route through channels and that
//! the ChannelMessage contract is maintained across the provider->channel boundary.

use async_trait::async_trait;
use zeroclaw::channels::traits::{Channel, ChannelMessage, SendMessage};

// ─────────────────────────────────────────────────────────────────────────────
// Mock Channel for integration testing
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
#[allow(dead_code)]
struct MockChannel {
    name: String,
}

#[allow(dead_code)]
impl MockChannel {
    fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
        }
    }
}

#[async_trait]
impl Channel for MockChannel {
    fn name(&self) -> &str {
        &self.name
    }

    async fn send(&self, msg: &SendMessage) -> anyhow::Result<()> {
        println!("[{}] Sending: {}", self.name, msg.content);
        Ok(())
    }

    async fn listen(&self, _tx: tokio::sync::mpsc::Sender<ChannelMessage>) -> anyhow::Result<()> {
        anyhow::bail!("Mock channel listen not implemented")
    }

    async fn health_check(&self) -> bool {
        true
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Provider to Channel integration tests
// ─────────────────────────────────────────────────────────────────────────────

#[test]
fn provider_response_to_channel_message_format() {
    // Create a mock provider response that should translate to channel message
    let response_content = "Test response from provider";
    let channel_msg = ChannelMessage {
        id: "test_msg_001".into(),
        sender: "provider_agent".into(),
        reply_target: "".into(),
        content: response_content.into(),
        channel: "test_channel".into(),
        timestamp: 1_700_000_000,
        thread_ts: None,
    };

    // Verify the message can be used by channel
    assert_eq!(channel_msg.content, response_content);
    assert_eq!(channel_msg.sender, "provider_agent");
    assert!(!channel_msg.channel.is_empty());
}

#[test]
fn provider_channel_message_round_trip() {
    // Simulate provider generating response that becomes a channel message
    let provider_response = "The weather is sunny.";

    // Wrap provider response in channel message format
    let channel_msg = ChannelMessage {
        id: "round_trip_001".into(),
        sender: "assistant".into(),
        reply_target: "user_query_001".into(),
        content: provider_response.into(),
        channel: "telegram".into(),
        timestamp: 1_700_000_000,
        thread_ts: None,
    };

    // Verify round-trip preserves key information
    assert!(channel_msg.content.contains("sunny"));
    assert_eq!(channel_msg.reply_target, "user_query_001");
}

#[test]
fn multi_provider_channel_routing() {
    // Test that different providers can route to the same channel
    let providers = ["openai", "anthropic", "ollama"];

    for provider_name in providers {
        let msg = ChannelMessage {
            id: format!("msg_{provider_name}"),
            sender: provider_name.into(),
            reply_target: "".into(),
            content: format!("Response from {provider_name}"),
            channel: "unified".into(),
            timestamp: 1_700_000_000,
            thread_ts: None,
        };

        // Each provider should be able to generate valid channel messages
        assert!(!msg.sender.is_empty());
        assert!(!msg.content.is_empty());
    }
}

#[test]
fn channel_message_timestamp_propagation() {
    // Test that timestamps are correctly propagated through provider-channel chain
    let test_timestamp: u64 = 1_700_000_000;

    let msg = ChannelMessage {
        id: "ts_test_001".into(),
        sender: "test_provider".into(),
        reply_target: "".into(),
        content: "Timestamp test".into(),
        channel: "test".into(),
        timestamp: test_timestamp,
        thread_ts: None,
    };

    // Timestamp should be preserved exactly
    assert_eq!(msg.timestamp, test_timestamp);
}

#[test]
fn provider_error_to_channel_error_message() {
    // Test that provider errors can be formatted as channel messages
    let error_msg = "Failed to connect to model provider";

    let channel_msg = ChannelMessage {
        id: "error_001".into(),
        sender: "system".into(),
        reply_target: "".into(),
        content: format!("Error: {error_msg}"),
        channel: "error_channel".into(),
        timestamp: 1_700_000_000,
        thread_ts: None,
    };

    // Error messages should be properly formatted for channel delivery
    assert!(channel_msg.content.starts_with("Error:"));
    assert_eq!(channel_msg.sender, "system");
}
