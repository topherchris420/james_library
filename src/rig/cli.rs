//! `rain rig …` command handling.

use super::action::{
    ActionBoundary, ActionKind, ActionPolicy, ActionProposal, DispositionLog, ProposalOrigin,
};
use super::context::RigContext;
use super::inbox::{self, InboxDisposition};
use super::skybridge::frame::{MAX_FRAME_LEN, MAX_PAYLOAD, StationId};
use super::skybridge::modem::ModemConfig;
use super::skybridge::{BasebandSink, BasebandSource, SkybridgeTransport, radio};
use super::transport::RigTransport;
use super::transport::discovery::{InstallFacts, LXMF_MAX_PAYLOAD, configured_bridge};
use super::transport::reticulum::LxmfTransport;
use super::{doctor, render, setup, status, up};
use crate::config::{Config, RigPrivacyMode, RigProfileKind};
use crate::{RigCommands, RigRadioCommands};
use anyhow::{Context, Result, anyhow, bail};
use std::path::{Path, PathBuf};

fn print_json<T: serde::Serialize>(value: &T) -> Result<()> {
    println!("{}", serde_json::to_string_pretty(value)?);
    Ok(())
}

fn disposition_log(ctx: &RigContext) -> DispositionLog {
    DispositionLog::new(ctx.state_dir().join("dispositions.jsonl"))
}

/// Dispatch a `rain rig` subcommand.
pub async fn handle_command(
    command: RigCommands,
    library: Option<PathBuf>,
    config: Config,
) -> Result<()> {
    let ctx = RigContext::from_runtime(&config, library.as_deref());
    match command {
        RigCommands::Status { json } => {
            let snapshot = status::collect(&ctx).await;
            if json {
                print_json(&snapshot)
            } else {
                print!("{}", render::status(&snapshot));
                Ok(())
            }
        }
        RigCommands::Doctor { json } => {
            let report = doctor::run(&ctx).await;
            if json {
                print_json(&report)?;
            } else {
                print!("{}", render::doctor(&report));
            }
            if report.summary.fail > 0 {
                bail!("rig doctor: {} check(s) failed", report.summary.fail);
            }
            Ok(())
        }
        RigCommands::Models { json } => {
            let mut statuses = super::inference::probe_all(&ctx).await;
            statuses.extend(
                super::research::probe_research(&ctx)
                    .await
                    .into_iter()
                    .filter(|cap| cap.id == "lab-meeting"),
            );
            if json {
                print_json(&statuses)
            } else {
                print!(
                    "{}",
                    render::models(&statuses, ctx.config.default_model.as_deref())
                );
                Ok(())
            }
        }
        RigCommands::Capabilities { json } => {
            let statuses = status::collect_capabilities(&ctx).await;
            if json {
                print_json(&statuses)
            } else {
                print!("{}", render::capabilities(&statuses));
                Ok(())
            }
        }
        RigCommands::Peers { json } => {
            let snapshot = status::collect(&ctx).await;
            let allowed = ctx.config.node_transport.allowed_peers.len();
            let seen = match configured_bridge(&ctx) {
                None => render::PeersSeen::BridgeDisabled,
                Some(bridge) => match bridge.connect().await {
                    Ok(mut session) => match session.peers().await {
                        Ok(peers) => render::PeersSeen::Seen(peers),
                        Err(error) => render::PeersSeen::Unreachable(error.to_string()),
                    },
                    Err(error) => render::PeersSeen::Unreachable(error.to_string()),
                },
            };
            if json {
                let transports: Vec<_> = ["reticulum", "lxmf", "skybridge", "local-network"]
                    .iter()
                    .filter_map(|id| snapshot.get(id))
                    .collect();
                print_json(&serde_json::json!({
                    "identity": snapshot.identity,
                    "transports": transports,
                    "node_transport_allowed_peers": allowed,
                    "bridge": match &seen {
                        render::PeersSeen::BridgeDisabled => "disabled",
                        render::PeersSeen::Unreachable(_) => "unreachable",
                        render::PeersSeen::Seen(_) => "connected",
                    },
                    "peers_seen": match &seen {
                        render::PeersSeen::Seen(peers) => peers.clone(),
                        _ => Vec::new(),
                    },
                }))
            } else {
                let identity = serde_json::to_string(&snapshot.identity)?;
                print!("{}", render::peers(&snapshot, &identity, allowed, &seen));
                Ok(())
            }
        }
        RigCommands::Send {
            transport,
            to,
            text,
        } => send_message(&ctx, &transport, to, text).await,
        RigCommands::Receive { max, json } => receive_messages(&ctx, max, json).await,
        RigCommands::Setup {
            profile,
            node_name,
            privacy,
            yes,
            dry_run,
        } => {
            let request = setup::SetupRequest {
                profile: profile
                    .as_deref()
                    .map(|raw| {
                        RigProfileKind::parse(raw).ok_or_else(|| anyhow!("unknown profile {raw}"))
                    })
                    .transpose()?,
                node_name,
                privacy: privacy
                    .as_deref()
                    .map(|raw| {
                        RigPrivacyMode::parse(raw)
                            .ok_or_else(|| anyhow!("unknown privacy mode {raw}"))
                    })
                    .transpose()?,
                yes,
                dry_run,
            };
            Box::pin(setup::run(&config, &ctx, request)).await
        }
        RigCommands::Up { dry_run } => Box::pin(up::run(config, &ctx, dry_run)).await,
        RigCommands::Radio { radio_command } => radio_command_handler(radio_command, &ctx).await,
    }
}

/// LXMF adapter for the configured bridge; errors when the bridge is disabled.
fn lxmf_transport(
    ctx: &RigContext,
) -> Result<(LxmfTransport, super::transport::bridge::BridgeClient)> {
    let bridge = configured_bridge(ctx).ok_or_else(|| {
        anyhow!(
            "the Reticulum/LXMF bridge is disabled; set [rig.bridge] enabled = true in config.toml, then run `rain rig up`"
        )
    })?;
    Ok((
        LxmfTransport::from_discovery(InstallFacts::default(), Some(bridge.clone())),
        bridge,
    ))
}

async fn send_message(ctx: &RigContext, transport: &str, to: String, text: String) -> Result<()> {
    if transport != "lxmf" {
        bail!("unsupported transport '{transport}'");
    }
    let (lxmf, bridge) = lxmf_transport(ctx)?;
    // Fail before recording an authorization for a bridge that is down.
    bridge
        .connect()
        .await
        .map_err(|error| anyhow!("{error}"))
        .context("the Reticulum/LXMF bridge is not usable")?;
    let boundary = ActionBoundary::new(
        ActionPolicy::new(LXMF_MAX_PAYLOAD).allow_transport("lxmf"),
        Some(disposition_log(ctx)),
    );
    let proposal = ActionProposal::new(
        ProposalOrigin::Operator,
        ActionKind::TransportSend {
            transport: "lxmf".into(),
            destination: Some(to.clone()),
        },
        text.into_bytes(),
    );
    let (record, token) = boundary.submit(proposal, None);
    let Some(token) = token else {
        bail!(
            "not authorized: {}",
            record.reason.unwrap_or_else(|| "rejected".into())
        );
    };
    let receipt = lxmf
        .send(&token)
        .await
        .map_err(|error| anyhow!("{error}"))?;
    println!(
        "Queued {} B for LXMF address {to} (proposal {}).",
        receipt.bytes, receipt.proposal_id
    );
    println!("Delivery is asynchronous; the bridge retries while the peer is reachable.");
    println!(
        "Disposition recorded in {}.",
        disposition_log(ctx).path().display()
    );
    Ok(())
}

async fn receive_messages(ctx: &RigContext, max: u16, json: bool) -> Result<()> {
    let (lxmf, _) = lxmf_transport(ctx)?;
    let mut dispositions = Vec::new();
    for _ in 0..max {
        match lxmf.receive().await.map_err(|error| anyhow!("{error}"))? {
            Some(message) => dispositions.push(inbox::admit(&message)),
            None => break,
        }
    }
    if json {
        return print_json(&dispositions);
    }
    if dispositions.is_empty() {
        println!("No messages waiting.");
        return Ok(());
    }
    for disposition in &dispositions {
        match disposition {
            InboxDisposition::Admitted {
                source, request, ..
            } => match request {
                inbox::InboundRequest::Ping => println!("{source}  PING"),
                inbox::InboundRequest::IdentityQuery => println!("{source}  IDENTITY?"),
                inbox::InboundRequest::Note { text } => println!("{source}  note: {text}"),
            },
            InboxDisposition::Rejected { reason, .. } => {
                println!("(rejected by the restricted inbox: {reason:?})");
            }
        }
    }
    println!("\nInbound messages are inert data; nothing was executed and no reply was sent.");
    Ok(())
}

async fn radio_command_handler(command: RigRadioCommands, ctx: &RigContext) -> Result<()> {
    let modem = ModemConfig::default();
    match command {
        RigRadioCommands::Status { json } => {
            let backend = radio::active_backend();
            let summary = serde_json::json!({
                "extension": "skybridge",
                "experimental": true,
                "modulation": "continuous-phase BFSK (software baseband)",
                "sample_rate_hz": modem.sample_rate,
                "baud": modem.baud,
                "mark_hz": modem.mark_hz,
                "space_hz": modem.space_hz,
                "max_payload_bytes": MAX_PAYLOAD,
                "max_frame_bytes": MAX_FRAME_LEN,
                "max_frame_airtime_secs": modem.airtime_secs(MAX_FRAME_LEN),
                "integrity": "CRC-16/X.25 (error detection, not authentication)",
                "payload": "UTF-8 plaintext only (no encryption)",
                "rf_backend": backend.name(),
                "rf_transmit": backend.can_transmit(),
            });
            if json {
                return print_json(&summary);
            }
            println!("SKYBRIDGE [experimental] // software baseband modem\n");
            println!(
                "  modulation     continuous-phase BFSK, {} baud",
                modem.baud
            );
            println!(
                "  tones          mark {} Hz · space {} Hz · {} Hz sample rate",
                modem.mark_hz, modem.space_hz, modem.sample_rate
            );
            println!(
                "  frames         ≤ {MAX_PAYLOAD} B plaintext payload · ≤ {MAX_FRAME_LEN} B frame · ≤ {:.1} s airtime",
                modem.airtime_secs(MAX_FRAME_LEN)
            );
            println!("  integrity      CRC-16/X.25 (detects corruption; not authentication)");
            println!("  RF transmit    DISABLED · backend '{}'", backend.name());
            println!("\n  This build renders and decodes baseband audio files only. It cannot");
            println!("  key a transmitter, select a frequency, or control an SDR.");
            Ok(())
        }
        RigRadioCommands::Encode {
            station,
            text,
            out,
            force,
        } => {
            let station = StationId::parse(&station).map_err(|error| anyhow!("{error}"))?;
            if out.exists() && !force {
                bail!(
                    "{} already exists; pass --force to overwrite",
                    out.display()
                );
            }
            let boundary = ActionBoundary::new(
                ActionPolicy::new(MAX_PAYLOAD).allow_transport("skybridge"),
                Some(disposition_log(ctx)),
            );
            let proposal = ActionProposal::new(
                ProposalOrigin::Operator,
                ActionKind::TransportSend {
                    transport: "skybridge".into(),
                    destination: None,
                },
                text.into_bytes(),
            );
            let (record, token) = boundary.submit(proposal, None);
            let Some(token) = token else {
                bail!(
                    "not authorized: {}",
                    record.reason.unwrap_or_else(|| "rejected".into())
                );
            };
            let transport = SkybridgeTransport::new(station, modem)
                .with_sink(BasebandSink::WavFile(out.clone()));
            let receipt = transport
                .send(&token)
                .await
                .map_err(|error| anyhow!("{error}"))?;
            println!(
                "Wrote {} ({} B payload · proposal {}).",
                out.display(),
                receipt.bytes,
                receipt.proposal_id
            );
            println!(
                "Baseband audio file only — nothing was transmitted. RF transmit is disabled."
            );
            println!(
                "Disposition recorded in {}.",
                disposition_log(ctx).path().display()
            );
            Ok(())
        }
        RigRadioCommands::Decode { input, json } => decode(&input, json, modem).await,
    }
}

async fn decode(input: &Path, json: bool, modem: ModemConfig) -> Result<()> {
    // Receiving uses a placeholder local station; it is never transmitted.
    let station = StationId::parse("RX").map_err(|error| anyhow!("{error}"))?;
    let transport = SkybridgeTransport::new(station, modem)
        .with_source(BasebandSource::WavFile(input.to_path_buf()));
    let message = transport
        .receive()
        .await
        .map_err(|error| anyhow!("{error}"))
        .with_context(|| format!("decoding {}", input.display()))?;
    let Some(message) = message else {
        bail!("no Skybridge frame found in {}", input.display());
    };
    let disposition = inbox::admit(&message);
    if json {
        return print_json(&disposition);
    }
    match &disposition {
        InboxDisposition::Admitted {
            source, request, ..
        } => {
            println!("Frame from station {source} admitted as {request:?}.");
            println!("Inbound messages are inert data; nothing was executed.");
        }
        InboxDisposition::Rejected { reason, .. } => {
            println!("Frame rejected by the restricted inbox: {reason:?}");
        }
    }
    Ok(())
}
