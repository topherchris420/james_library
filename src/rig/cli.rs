//! `rain rig …` command handling.

use super::action::{
    ActionBoundary, ActionKind, ActionPolicy, ActionProposal, DispositionLog, ProposalOrigin,
};
use super::context::RigContext;
use super::inbox::{self, InboundMessage, InboxDisposition};
use super::skybridge::fragment::MAX_MESSAGE_BYTES;
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
            let radio_config = ctx.config.rig.radio.as_ref();
            let backend = radio::transmit_backend(radio_config, &ctx.state_dir());
            let unavailable = radio::transmit_unavailable(radio_config);
            let receive = radio_config
                .and_then(|r| r.receive.first().cloned())
                .unwrap_or_default();
            let summary = serde_json::json!({
                "extension": "skybridge",
                "experimental": true,
                "modulation": "continuous-phase BFSK (software baseband)",
                "sample_rate_hz": modem.sample_rate,
                "baud": modem.baud,
                "mark_hz": modem.mark_hz,
                "space_hz": modem.space_hz,
                "max_payload_bytes": MAX_PAYLOAD,
                "max_message_bytes": MAX_MESSAGE_BYTES,
                "max_frame_bytes": MAX_FRAME_LEN,
                "max_frame_airtime_secs": modem.airtime_secs(MAX_FRAME_LEN),
                "fec": modem.coding,
                "integrity": "CRC-16/X.25 (error detection, not authentication)",
                "payload": "UTF-8 plaintext only (no encryption)",
                "receive_command": if receive.is_empty() { None } else { Some(&receive) },
                "rf_transmit_compiled": crate::rig::action::RF_TRANSMIT_COMPILED,
                "rf_backend": backend.name(),
                "rf_transmit": backend.can_transmit(),
                "rf_transmit_disabled_reason": unavailable,
                "band_plan": crate::rig::action::RF_BAND_PLAN
                    .iter()
                    .map(|b| serde_json::json!({"band": b.name, "low_hz": b.low_hz, "high_hz": b.high_hz}))
                    .collect::<Vec<_>>(),
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
            println!(
                "  messages       ≤ {MAX_MESSAGE_BYTES} B, fragmented over consecutive frames"
            );
            println!(
                "  FEC            {} (decoder accepts coded and plain frames)",
                modem.coding.label()
            );
            println!("  integrity      CRC-16/X.25 (detects corruption; not authentication)");
            if receive.is_empty() {
                println!("  receive        not configured ([rig.radio] receive)");
            } else {
                println!("  receive        `{receive}` (receive only)");
            }
            match unavailable {
                Some(reason) => println!("  RF transmit    DISABLED · {reason}"),
                None => {
                    println!(
                        "  RF transmit    ENABLED · backend '{}' · callsign {} · ≤ {} W",
                        backend.name(),
                        radio_config
                            .and_then(|r| r.callsign.as_deref())
                            .unwrap_or("?"),
                        radio_config.and_then(|r| r.max_power_w).unwrap_or(0)
                    );
                    println!(
                        "                 every transmission needs the operator's typed callsign"
                    );
                }
            }
            let bands: Vec<&str> = crate::rig::action::RF_BAND_PLAN
                .iter()
                .map(|b| b.name)
                .collect();
            println!(
                "  band plan      {} (common to ITU regions 1-3; an outer bound, not a licence)",
                bands.join(" ")
            );
            Ok(())
        }
        RigRadioCommands::Encode {
            station,
            text,
            out,
            force,
            no_fec,
        } => {
            let modem = ModemConfig {
                coding: if no_fec {
                    super::skybridge::modem::Coding::Plain
                } else {
                    super::skybridge::modem::Coding::Hamming74
                },
                ..modem
            };
            let station = StationId::parse(&station).map_err(|error| anyhow!("{error}"))?;
            if out.exists() && !force {
                bail!(
                    "{} already exists; pass --force to overwrite",
                    out.display()
                );
            }
            let boundary = ActionBoundary::new(
                ActionPolicy::new(MAX_MESSAGE_BYTES).allow_transport("skybridge"),
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
        RigRadioCommands::Listen { seconds, json } => listen(ctx, seconds, json, modem).await,
        RigRadioCommands::Transmit {
            text,
            frequency_hz,
            power_w,
        } => transmit(ctx, text, frequency_hz, power_w, modem).await,
    }
}

async fn decode(input: &Path, json: bool, modem: ModemConfig) -> Result<()> {
    // Receiving uses a placeholder local station; it is never transmitted.
    let station = StationId::parse("RX").map_err(|error| anyhow!("{error}"))?;
    let transport = SkybridgeTransport::new(station, modem)
        .with_source(BasebandSource::WavFile(input.to_path_buf()));
    let mut messages = Vec::new();
    while let Some(message) = transport
        .receive()
        .await
        .map_err(|error| anyhow!("{error}"))
        .with_context(|| format!("decoding {}", input.display()))?
    {
        messages.push(message);
    }
    if messages.is_empty() {
        bail!("no complete Skybridge message found in {}", input.display());
    }
    report_skybridge_messages(&messages, json)
}

/// Operator-only RF transmit: boundary checks, typed-callsign confirmation,
/// recorded disposition, then the configured backend.
async fn transmit(
    ctx: &RigContext,
    text: String,
    frequency_hz: u64,
    power_w: u16,
    modem: ModemConfig,
) -> Result<()> {
    use super::action::{HumanApproval, RadioPolicy, band_for};
    use std::io::{BufRead, IsTerminal, Write};

    let radio_config = ctx.config.rig.radio.as_ref();
    let callsign = radio_config
        .and_then(|r| r.callsign.clone())
        .unwrap_or_default();
    let mut policy = ActionPolicy::new(MAX_MESSAGE_BYTES);
    if let (Some(radio), Some(max_power_w)) =
        (radio_config, radio_config.and_then(|r| r.max_power_w))
    {
        if let Some(licensed_callsign) = radio.callsign.clone() {
            policy = policy.with_radio(RadioPolicy {
                licensed_callsign,
                max_power_w,
            });
        }
    }
    let boundary = ActionBoundary::new(policy, Some(disposition_log(ctx)));
    let proposal = ActionProposal::new(
        ProposalOrigin::Operator,
        ActionKind::RadioTransmit {
            callsign: callsign.clone(),
            frequency_hz,
            power_w,
        },
        text.into_bytes(),
    );
    // First pass: every deterministic check, no approval yet.
    let (record, _) = boundary.submit(proposal.clone(), None);
    if record.disposition != super::action::Disposition::AwaitingHumanAuthorization {
        bail!(
            "not authorized: {}",
            record.reason.unwrap_or_else(|| "rejected".into())
        );
    }
    let backend = radio::transmit_backend(radio_config, &ctx.state_dir().join("tx"));
    if !backend.can_transmit() {
        bail!(
            "RF transmit is disabled: {}",
            radio::transmit_unavailable(radio_config).unwrap_or("no backend")
        );
    }
    let station = StationId::parse(&callsign).map_err(|error| anyhow!("{error}"))?;
    let transport = SkybridgeTransport::new(station, modem);
    let (frames, samples) = transport
        .render(&proposal.payload)
        .map_err(|error| anyhow!("{error}"))?;
    let airtime = samples.len() as f32 / modem.sample_rate as f32;

    if !std::io::stdin().is_terminal() {
        bail!("RF transmit requires an interactive terminal confirmation; nothing was transmitted");
    }
    let band = band_for(frequency_hz).map_or("?", |b| b.name);
    println!("RF TRANSMIT — review before confirming\n");
    println!("  callsign   {callsign} (station id on air)");
    println!(
        "  frequency  {:.3} kHz USB dial · {band} band",
        frequency_hz as f64 / 1000.0
    );
    println!("  power      {power_w} W");
    println!(
        "  message    {} B plaintext · {} frame(s) · {:.1} s airtime · {}",
        proposal.payload.len(),
        frames.len(),
        airtime,
        modem.coding.label()
    );
    println!("  backend    {}\n", backend.name());
    println!("You are responsible for holding a licence that covers this band, mode and power.");
    print!("Type your callsign to transmit (anything else cancels): ");
    std::io::stdout().flush()?;
    let mut typed = String::new();
    std::io::stdin().lock().read_line(&mut typed)?;
    if typed.trim().to_ascii_uppercase() != callsign {
        bail!("cancelled; nothing was transmitted");
    }
    let approval = HumanApproval::confirmed_by_operator(&proposal.id);
    let (record, token) = boundary.submit(proposal, Some(&approval));
    let Some(token) = token else {
        bail!(
            "not authorized: {}",
            record.reason.unwrap_or_else(|| "rejected".into())
        );
    };
    let result = tokio::task::spawn_blocking(move || backend.transmit(&samples, &token))
        .await
        .map_err(|error| anyhow!("transmit task failed: {error}"))?;
    result.map_err(|error| anyhow!("{error}"))?;
    println!(
        "Transmitted {} frame(s) ({:.1} s). Disposition recorded in {}.",
        frames.len(),
        airtime,
        disposition_log(ctx).path().display()
    );
    Ok(())
}

async fn listen(ctx: &RigContext, seconds: u64, json: bool, modem: ModemConfig) -> Result<()> {
    let argv = ctx
        .config
        .rig
        .radio
        .as_ref()
        .map(|radio| radio.receive.clone())
        .filter(|argv| !argv.is_empty())
        .ok_or_else(|| {
            anyhow!(
                "no receive command configured; set [rig.radio] receive, for example\n  \
                 receive = [\"rtl_fm\", \"-f\", \"14.1M\", \"-M\", \"usb\", \"-s\", \"8000\", \"-\"]"
            )
        })?;
    if !json {
        eprintln!(
            "Listening for {seconds} s with `{}` (receive only; nothing is transmitted)…",
            argv[0]
        );
    }
    let station = StationId::parse("RX").map_err(|error| anyhow!("{error}"))?;
    let transport = SkybridgeTransport::new(station, modem)
        .with_source(BasebandSource::Command { argv, seconds });
    let mut messages = Vec::new();
    loop {
        match transport.receive().await {
            Ok(Some(message)) => messages.push(message),
            Ok(None) => break,
            // A capture window that cuts a frame, or noise that fails the CRC,
            // is normal on a live receiver: report it, keep what decoded.
            Err(super::transport::TransportError::Malformed(detail)) => {
                eprintln!("No further complete frame ({detail}).");
                break;
            }
            Err(error) => return Err(anyhow!("{error}")),
        }
    }
    if messages.is_empty() && !json {
        println!("No complete Skybridge message received.");
        return Ok(());
    }
    report_skybridge_messages(&messages, json)
}

/// Admit decoded Skybridge messages through the restricted inbox and report.
fn report_skybridge_messages(messages: &[InboundMessage], json: bool) -> Result<()> {
    let dispositions: Vec<InboxDisposition> = messages.iter().map(inbox::admit).collect();
    if json {
        return print_json(&dispositions);
    }
    for disposition in &dispositions {
        match disposition {
            InboxDisposition::Admitted {
                source, request, ..
            } => println!("Message from station {source} admitted as {request:?}."),
            InboxDisposition::Rejected { reason, .. } => {
                println!("Message rejected by the restricted inbox: {reason:?}");
            }
        }
    }
    println!("Inbound messages are inert data; nothing was executed.");
    Ok(())
}
