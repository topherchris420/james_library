//! Client for the R.A.I.N.-owned Reticulum/LXMF bridge sidecar
//! (`tools/rig_bridge/bridge.py`).
//!
//! The sidecar is a separate Python process so Reticulum is never linked
//! into `rain`. The client:
//!
//! - connects to `127.0.0.1` only (the address is not configurable);
//! - authenticates both ends with an HMAC-SHA256 challenge keyed by the token
//!   in `<workspace>/rig/bridge.token`, refusing a token file other users can
//!   read; the token never crosses the socket, so a process squatting the
//!   port learns nothing and cannot pass the server check;
//! - bounds every line, request, and connect by size and time;
//! - treats every reply as untrusted: addresses are re-validated, names are
//!   sanitized, and inbound text goes back through
//!   [`inbox::admit`](crate::rig::inbox::admit) at the caller.

use super::TransportError;
use crate::rig::action::is_lxmf_address;
use crate::rig::inbox::InboundMessage;
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::path::PathBuf;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::net::tcp::{OwnedReadHalf, OwnedWriteHalf};

pub const BRIDGE_PROTOCOL: &str = "rain-rig-bridge";
pub const BRIDGE_VERSION: u64 = 1;
pub const TOKEN_FILE: &str = "bridge.token";
const MAX_LINE_BYTES: u64 = 16 * 1024;
const MAX_PEER_NAME: usize = 32;
const CONNECT_TIMEOUT: Duration = Duration::from_millis(800);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);

type HmacSha256 = Hmac<Sha256>;

fn io(error: impl std::fmt::Display) -> TransportError {
    TransportError::Io(format!("bridge: {error}"))
}

fn proto(detail: impl std::fmt::Display) -> TransportError {
    TransportError::Malformed(format!("bridge: {detail}"))
}

fn keyed_mac(token: &str, role: &str, nonce: &str, client_nonce: &str) -> HmacSha256 {
    // HMAC accepts keys of any length; this cannot fail.
    let mut mac = HmacSha256::new_from_slice(token.as_bytes()).expect("HMAC key");
    mac.update(
        format!("{BRIDGE_PROTOCOL}/v{BRIDGE_VERSION}/{role}|{nonce}|{client_nonce}").as_bytes(),
    );
    mac
}

fn is_hex(value: &str, len: usize) -> bool {
    value.len() == len && value.bytes().all(|b| b.is_ascii_hexdigit())
}

/// Read the shared token, refusing files other users could read.
fn read_token(path: &std::path::Path) -> Result<String, TransportError> {
    let metadata = std::fs::metadata(path).map_err(|_| {
        TransportError::Io(format!(
            "bridge: no token at {} (is the bridge running? start it with `rain rig up`)",
            path.display()
        ))
    })?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(io(format!(
                "token file {} is accessible to other users; refusing it (expected mode 0600)",
                path.display()
            )));
        }
    }
    #[cfg(not(unix))]
    let _ = metadata;
    let token = std::fs::read_to_string(path).map_err(io)?;
    let token = token.trim();
    if !is_hex(token, 64) {
        return Err(proto("token file is malformed"));
    }
    Ok(token.to_string())
}

/// Where and how to reach the bridge.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BridgeClient {
    port: u16,
    token_path: PathBuf,
}

impl BridgeClient {
    pub fn new(port: u16, state_dir: &std::path::Path) -> Self {
        Self {
            port,
            token_path: state_dir.join(TOKEN_FILE),
        }
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn endpoint(&self) -> String {
        format!("127.0.0.1:{}", self.port)
    }

    /// Connect and complete the mutual handshake.
    pub async fn connect(&self) -> Result<BridgeSession, TransportError> {
        let token = read_token(&self.token_path)?;
        let stream = tokio::time::timeout(
            CONNECT_TIMEOUT,
            TcpStream::connect(("127.0.0.1", self.port)),
        )
        .await
        .map_err(|_| io(format!("connect to {} timed out", self.endpoint())))?
        .map_err(|error| io(format!("{} not reachable ({error})", self.endpoint())))?;
        let (read, write) = stream.into_split();
        let mut session = BridgeSession {
            reader: BufReader::new(read),
            writer: write,
        };
        tokio::time::timeout(REQUEST_TIMEOUT, session.handshake(&token))
            .await
            .map_err(|_| io("handshake timed out"))??;
        Ok(session)
    }
}

/// Bridge-reported status.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct BridgeStatus {
    #[serde(default)]
    pub backend: String,
    #[serde(default)]
    pub lxmf_address: Option<String>,
    #[serde(default)]
    pub shared_instance: bool,
    #[serde(default)]
    pub interfaces: u64,
    #[serde(default)]
    pub queued_inbound: u64,
    #[serde(default)]
    pub dropped_inbound: u64,
    #[serde(default)]
    pub peers: u64,
}

/// A peer seen via an LXMF announce. `name` is untrusted and sanitized.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BridgePeer {
    pub hash: String,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub last_seen: i64,
}

/// Strip control and bidirectional characters and cap the length.
pub fn sanitize_peer_name(raw: &str) -> Option<String> {
    let cleaned: String = raw
        .chars()
        .filter(|c| !c.is_control() && !('\u{202A}'..='\u{2069}').contains(c))
        .take(MAX_PEER_NAME)
        .collect();
    let cleaned = cleaned.trim();
    (!cleaned.is_empty()).then(|| cleaned.to_string())
}

/// An authenticated connection.
#[derive(Debug)]
pub struct BridgeSession {
    reader: BufReader<OwnedReadHalf>,
    writer: OwnedWriteHalf,
}

impl BridgeSession {
    async fn read_json(&mut self) -> Result<serde_json::Value, TransportError> {
        let mut line = Vec::new();
        (&mut self.reader)
            .take(MAX_LINE_BYTES + 1)
            .read_until(b'\n', &mut line)
            .await
            .map_err(io)?;
        if line.is_empty() {
            return Err(io("connection closed"));
        }
        if line.len() as u64 > MAX_LINE_BYTES || line.last() != Some(&b'\n') {
            return Err(proto("reply line too long"));
        }
        serde_json::from_slice(&line).map_err(|error| proto(format!("invalid JSON ({error})")))
    }

    async fn write_json(&mut self, value: &serde_json::Value) -> Result<(), TransportError> {
        let mut line = serde_json::to_vec(value).map_err(proto)?;
        line.push(b'\n');
        self.writer.write_all(&line).await.map_err(io)?;
        self.writer.flush().await.map_err(io)
    }

    async fn handshake(&mut self, token: &str) -> Result<(), TransportError> {
        let greeting = self.read_json().await?;
        if greeting["bridge"] != BRIDGE_PROTOCOL || greeting["version"] != BRIDGE_VERSION {
            return Err(proto("not a R.A.I.N. bridge (protocol mismatch)"));
        }
        let nonce = greeting["nonce"]
            .as_str()
            .filter(|nonce| is_hex(nonce, 32))
            .ok_or_else(|| proto("missing nonce"))?
            .to_string();
        let client_nonce = hex::encode(rand::random::<[u8; 16]>());
        let client_mac = keyed_mac(token, "client", &nonce, &client_nonce).finalize();
        self.write_json(&serde_json::json!({
            "op": "hello",
            "client_nonce": client_nonce,
            "mac": hex::encode(client_mac.into_bytes()),
        }))
        .await?;
        let reply = self.read_json().await?;
        if reply["ok"] != true {
            return Err(io(
                "authentication refused (token mismatch; restart the bridge)",
            ));
        }
        let server_mac = reply["mac"]
            .as_str()
            .and_then(|mac| hex::decode(mac).ok())
            .ok_or_else(|| proto("missing server proof"))?;
        keyed_mac(token, "server", &nonce, &client_nonce)
            .verify_slice(&server_mac)
            .map_err(|_| io("server failed authentication (not the R.A.I.N. bridge)"))
    }

    /// Send one request and return the `ok` reply.
    pub async fn request(
        &mut self,
        request: serde_json::Value,
    ) -> Result<serde_json::Value, TransportError> {
        tokio::time::timeout(REQUEST_TIMEOUT, async {
            self.write_json(&request).await?;
            let reply = self.read_json().await?;
            if reply["ok"] == true {
                Ok(reply)
            } else {
                let error = reply["error"].as_str().unwrap_or("request refused");
                Err(io(error.chars().take(200).collect::<String>()))
            }
        })
        .await
        .map_err(|_| io("request timed out"))?
    }

    pub async fn status(&mut self) -> Result<BridgeStatus, TransportError> {
        let reply = self.request(serde_json::json!({ "op": "status" })).await?;
        let mut status: BridgeStatus = serde_json::from_value(reply).map_err(proto)?;
        status.lxmf_address = status.lxmf_address.filter(|a| is_lxmf_address(a));
        status.backend = sanitize_peer_name(&status.backend).unwrap_or_default();
        Ok(status)
    }

    pub async fn peers(&mut self) -> Result<Vec<BridgePeer>, TransportError> {
        let reply = self.request(serde_json::json!({ "op": "peers" })).await?;
        let peers: Vec<BridgePeer> =
            serde_json::from_value(reply["peers"].clone()).map_err(proto)?;
        Ok(peers
            .into_iter()
            .filter(|peer| is_lxmf_address(&peer.hash))
            .map(|peer| BridgePeer {
                name: peer.name.as_deref().and_then(sanitize_peer_name),
                ..peer
            })
            .collect())
    }

    /// Queue an LXMF message. Returns the LXMF message id when reported.
    pub async fn send(&mut self, to: &str, text: &str) -> Result<Option<String>, TransportError> {
        let reply = self
            .request(serde_json::json!({ "op": "send", "to": to, "text": text }))
            .await?;
        Ok(reply["message_id"]
            .as_str()
            .filter(|id| is_hex(id, 64))
            .map(str::to_string))
    }

    /// Next queued inbound message, as raw input for the restricted inbox.
    pub async fn recv(&mut self) -> Result<Option<InboundMessage>, TransportError> {
        let reply = self.request(serde_json::json!({ "op": "recv" })).await?;
        let message = &reply["message"];
        if message.is_null() {
            return Ok(None);
        }
        let source = message["source"]
            .as_str()
            .filter(|source| is_lxmf_address(source))
            .ok_or_else(|| proto("inbound message has an invalid source"))?;
        let text = message["text"]
            .as_str()
            .ok_or_else(|| proto("inbound message has no text"))?;
        Ok(Some(InboundMessage {
            transport: "lxmf".into(),
            source: source.to_string(),
            payload: text.as_bytes().to_vec(),
        }))
    }
}

#[cfg(test)]
pub(crate) mod test_support {
    //! In-process fake bridge speaking the sidecar protocol.
    use super::*;
    use tokio::net::TcpListener;

    pub const TOKEN: &str = "5f4dcc3b5aa765d61d8327deb882cf995f4dcc3b5aa765d61d8327deb882cf99";

    pub fn write_token(dir: &std::path::Path, token: &str) {
        std::fs::create_dir_all(dir).unwrap();
        let path = dir.join(TOKEN_FILE);
        std::fs::write(&path, token).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        }
    }

    /// Serve one connection with `server_token`, answering with `replies`
    /// in order and recording the requests it received.
    pub async fn fake_bridge(
        server_token: &'static str,
        replies: Vec<serde_json::Value>,
    ) -> (u16, tokio::task::JoinHandle<Vec<serde_json::Value>>) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let (read, mut write) = stream.into_split();
            let mut lines = BufReader::new(read).lines();
            let nonce = "00112233445566778899aabbccddeeff";
            let greeting =
                serde_json::json!({"bridge": BRIDGE_PROTOCOL, "version": 1, "nonce": nonce});
            write
                .write_all(format!("{greeting}\n").as_bytes())
                .await
                .unwrap();
            let hello: serde_json::Value =
                serde_json::from_str(&lines.next_line().await.unwrap().unwrap()).unwrap();
            let client_nonce = hello["client_nonce"].as_str().unwrap().to_string();
            let expected = hex::encode(
                keyed_mac(server_token, "client", nonce, &client_nonce)
                    .finalize()
                    .into_bytes(),
            );
            if hello["mac"] != expected.as_str() {
                let _ = write
                    .write_all(b"{\"ok\":false,\"error\":\"unauthorized\"}\n")
                    .await;
                return Vec::new();
            }
            let proof = hex::encode(
                keyed_mac(server_token, "server", nonce, &client_nonce)
                    .finalize()
                    .into_bytes(),
            );
            let ok = serde_json::json!({"ok": true, "mac": proof});
            write.write_all(format!("{ok}\n").as_bytes()).await.unwrap();
            let mut seen = Vec::new();
            for reply in replies {
                let Ok(Some(line)) = lines.next_line().await else {
                    break;
                };
                seen.push(serde_json::from_str(&line).unwrap());
                write
                    .write_all(format!("{reply}\n").as_bytes())
                    .await
                    .unwrap();
            }
            seen
        });
        (port, handle)
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::*;
    use super::*;

    const PEER: &str = "0123456789abcdef0123456789abcdef";

    #[tokio::test]
    async fn authenticated_session_sanitizes_untrusted_replies() {
        let dir = tempfile::tempdir().unwrap();
        write_token(dir.path(), TOKEN);
        let (port, server) = fake_bridge(
            TOKEN,
            vec![
                serde_json::json!({"ok": true, "backend": "rns", "lxmf_address": "NOT HEX", "peers": 2}),
                serde_json::json!({"ok": true, "peers": [
                    {"hash": PEER, "name": "kit\u{202e}\u{7}-1", "last_seen": 1},
                    {"hash": "../../etc/passwd", "name": "x", "last_seen": 2}
                ]}),
                serde_json::json!({"ok": true, "message": {"source": PEER, "text": "PING"}}),
                serde_json::json!({"ok": true, "message": {"source": "bogus", "text": "x"}}),
                serde_json::json!({"ok": false, "error": "no path"}),
            ],
        )
        .await;
        let client = BridgeClient::new(port, dir.path());
        let mut session = client.connect().await.unwrap();
        let status = session.status().await.unwrap();
        assert_eq!(status.backend, "rns");
        assert_eq!(status.lxmf_address, None);
        let peers = session.peers().await.unwrap();
        assert_eq!(peers.len(), 1);
        assert_eq!(peers[0].name.as_deref(), Some("kit-1"));
        let message = session.recv().await.unwrap().unwrap();
        assert_eq!(
            (message.transport.as_str(), message.source.as_str()),
            ("lxmf", PEER)
        );
        assert!(session.recv().await.is_err());
        let error = session.send(PEER, "hi").await.unwrap_err().to_string();
        assert!(error.contains("no path"), "{error}");
        let seen = server.await.unwrap();
        assert_eq!(
            seen[4],
            serde_json::json!({"op": "send", "to": PEER, "text": "hi"})
        );
    }

    #[tokio::test]
    async fn impostor_without_the_token_is_rejected() {
        let dir = tempfile::tempdir().unwrap();
        write_token(dir.path(), TOKEN);
        // The impostor accepts any client MAC but cannot prove the token.
        let impostor = "1111111111111111111111111111111111111111111111111111111111111111";
        let (port, _server) = fake_bridge(impostor, vec![]).await;
        let error = BridgeClient::new(port, dir.path())
            .connect()
            .await
            .unwrap_err()
            .to_string();
        assert!(
            error.contains("token mismatch") || error.contains("authentication"),
            "{error}"
        );
    }

    #[tokio::test]
    async fn missing_token_or_unreachable_bridge_fails_cleanly() {
        let dir = tempfile::tempdir().unwrap();
        let error = BridgeClient::new(9, dir.path())
            .connect()
            .await
            .unwrap_err();
        assert!(error.to_string().contains("no token"), "{error}");
        write_token(dir.path(), TOKEN);
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        let error = BridgeClient::new(port, dir.path())
            .connect()
            .await
            .unwrap_err();
        assert!(error.to_string().contains("not reachable"), "{error}");
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn world_readable_token_is_refused() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().unwrap();
        write_token(dir.path(), TOKEN);
        let path = dir.path().join(TOKEN_FILE);
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        let error = BridgeClient::new(9, dir.path())
            .connect()
            .await
            .unwrap_err();
        assert!(error.to_string().contains("other users"), "{error}");
    }

    #[test]
    fn peer_names_are_sanitized() {
        assert_eq!(sanitize_peer_name("  \u{7}\u{202e} "), None);
        assert_eq!(
            sanitize_peer_name(&"n".repeat(80)).unwrap().len(),
            MAX_PEER_NAME
        );
    }
}
