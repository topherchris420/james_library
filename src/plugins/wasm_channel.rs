//! Bridge between WASM plugins and the Channel trait.

use crate::channels::traits::{Channel, ChannelMessage, SendMessage};
use async_trait::async_trait;

/// A channel backed by a WASM plugin.
pub struct WasmChannel {
    name: String,
    plugin_name: String,
}

impl WasmChannel {
    pub fn new(name: String, plugin_name: String) -> Self {
        Self { name, plugin_name }
    }
}

#[async_trait]
impl Channel for WasmChannel {
    fn name(&self) -> &str {
        &self.name
    }

    async fn send(&self, _message: &SendMessage) -> anyhow::Result<()> {
        anyhow::bail!(
            "WasmChannel '{}' (plugin: {}) — Extism send bridge not yet wired",
            self.name,
            self.plugin_name,
        )
    }

    async fn listen(&self, _tx: tokio::sync::mpsc::Sender<ChannelMessage>) -> anyhow::Result<()> {
        anyhow::bail!(
            "WasmChannel '{}' (plugin: {}) — Extism listen bridge not yet wired",
            self.name,
            self.plugin_name,
        )
    }
}
