#[allow(clippy::wildcard_imports)]
use crate::*;
use std::io::{self, IsTerminal, Write};

fn confirm_update(force: bool) -> Result<bool> {
    if force {
        return Ok(true);
    }

    if !io::stdin().is_terminal() {
        bail!(
            "refusing to run update without confirmation in non-interactive mode; pass --force to continue"
        );
    }

    print!("Proceed with update? [y/N]: ");
    io::stdout().flush()?;

    let mut answer = String::new();
    io::stdin().read_line(&mut answer)?;
    let trimmed = answer.trim().to_ascii_lowercase();
    Ok(trimmed == "y" || trimmed == "yes")
}

pub(crate) async fn dispatch_command(command: Commands, config: Config) -> Result<()> {
    match command {
        Commands::Onboard { .. } | Commands::Completions { .. } | Commands::LspQuery => {
            unreachable!()
        }

        Commands::Agent {
            message,
            session_state_file,
            provider,
            model,
            temperature,
            peripheral,
        } => {
            let final_temperature = temperature.unwrap_or(config.default_temperature);

            Box::pin(agent::run(
                config,
                message,
                provider,
                model,
                final_temperature,
                peripheral,
                true,
                session_state_file,
                None,
            ))
            .await
            .map(|_| ())
        }

        Commands::Gateway { gateway_command } => {
            match gateway_command {
                Some(rain_labs::GatewayCommands::Restart { port, host }) => {
                    let (port, host) = resolve_gateway_addr(&config, port, host);
                    let addr = format!("{host}:{port}");
                    info!("🔄 Restarting R.A.I.N. Gateway on {addr}");

                    // Try to gracefully shutdown existing gateway via admin endpoint
                    match shutdown_gateway(&host, port).await {
                        Ok(()) => {
                            info!("   ✓ Existing gateway on {addr} shut down gracefully");
                            // Poll until the port is free (connection refused) or timeout
                            let deadline =
                                tokio::time::Instant::now() + tokio::time::Duration::from_secs(5);
                            loop {
                                match tokio::net::TcpStream::connect(&addr).await {
                                    Err(_) => break, // port is free
                                    Ok(_) if tokio::time::Instant::now() >= deadline => {
                                        warn!(
                                            "   Timed out waiting for port {port} to be released"
                                        );
                                        break;
                                    }
                                    Ok(_) => {
                                        tokio::time::sleep(tokio::time::Duration::from_millis(50))
                                            .await;
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            info!("   No existing gateway to shut down: {e}");
                        }
                    }

                    log_gateway_start(&host, port);
                    Box::pin(gateway::run_gateway(&host, port, config)).await
                }
                Some(rain_labs::GatewayCommands::GetPaircode { new }) => {
                    let port = config.gateway.port;
                    let host = &config.gateway.host;

                    // Fetch live pairing code from running gateway
                    // If --new is specified, generate a fresh pairing code
                    match fetch_paircode(host, port, new).await {
                        Ok(Some(code)) => {
                            println!("🔐 Gateway pairing is enabled.");
                            println!();
                            println!("  ┌──────────────┐");
                            println!("  │  {code}  │");
                            println!("  └──────────────┘");
                            println!();
                            println!("  Use this one-time code to pair a new device:");
                            println!("    POST /pair with header X-Pairing-Code: {code}");
                        }
                        Ok(None) => {
                            if config.gateway.require_pairing {
                                println!(
                                    "🔐 Gateway pairing is enabled, but no active pairing code available."
                                );
                                println!(
                                    "   The gateway may already be paired, or the code has been used."
                                );
                                println!("   Restart the gateway to generate a new pairing code.");
                            } else {
                                println!("⚠️  Gateway pairing is disabled in config.");
                                println!(
                                    "   All requests will be accepted without authentication."
                                );
                                println!(
                                    "   To enable pairing, set [gateway] require_pairing = true"
                                );
                            }
                        }
                        Err(e) => {
                            println!(
                                "❌ Failed to fetch pairing code from gateway at {host}:{port}"
                            );
                            println!("   Error: {e}");
                            println!();
                            println!("   Is the gateway running? Start it with:");
                            println!("     rain gateway start");
                        }
                    }
                    Ok(())
                }
                Some(rain_labs::GatewayCommands::Start { port, host }) => {
                    let (port, host) = resolve_gateway_addr(&config, port, host);
                    log_gateway_start(&host, port);
                    Box::pin(gateway::run_gateway(&host, port, config)).await
                }
                None => {
                    let port = config.gateway.port;
                    let host = config.gateway.host.clone();
                    log_gateway_start(&host, port);
                    Box::pin(gateway::run_gateway(&host, port, config)).await
                }
            }
        }

        Commands::Daemon { port, host } => {
            let port = port.unwrap_or(config.gateway.port);
            let host = host.unwrap_or_else(|| config.gateway.host.clone());
            if port == 0 {
                info!("🧠 Starting R.A.I.N. Daemon on {host} (random port)");
            } else {
                info!("🧠 Starting R.A.I.N. Daemon on {host}:{port}");
            }
            Box::pin(daemon::run(config, host, port)).await
        }

        Commands::Status { format } => {
            if format.as_deref() == Some("exit-code") {
                // Lightweight health probe for Docker HEALTHCHECK
                let port = config.gateway.port;
                let host = if config.gateway.host == "[::]" || config.gateway.host == "0.0.0.0" {
                    "127.0.0.1"
                } else {
                    &config.gateway.host
                };
                let url = format!("http://{}:{}/health", host, port);
                match reqwest::Client::new()
                    .get(&url)
                    .timeout(std::time::Duration::from_secs(5))
                    .send()
                    .await
                {
                    Ok(resp) if resp.status().is_success() => {
                        std::process::exit(0);
                    }
                    _ => {
                        std::process::exit(1);
                    }
                }
            }
            println!("🦀 R.A.I.N. Status");
            println!();
            println!("Version:     {}", env!("CARGO_PKG_VERSION"));
            println!("Workspace:   {}", config.workspace_dir.display());
            println!("Config:      {}", config.config_path.display());
            println!();
            println!(
                "🤖 Provider:      {}",
                config.default_provider.as_deref().unwrap_or("openrouter")
            );
            println!(
                "   Model:         {}",
                config.default_model.as_deref().unwrap_or("(default)")
            );
            println!("📊 Observability:  {}", config.observability.backend);
            println!(
                "🧾 Trace storage:  {} ({})",
                config.observability.runtime_trace_mode, config.observability.runtime_trace_path
            );
            println!("🛡️  Autonomy:      {:?}", config.autonomy.level);
            println!("⚙️  Runtime:       {}", config.runtime.kind);
            if service::is_running() {
                println!("🟢 Service:       running");
            } else {
                println!("🔴 Service:       stopped");
            }
            let effective_memory_backend = memory::effective_memory_backend_name(
                &config.memory.backend,
                Some(&config.storage.provider.config),
            );
            println!(
                "💓 Heartbeat:      {}",
                if config.heartbeat.enabled {
                    format!("every {}min", config.heartbeat.interval_minutes)
                } else {
                    "disabled".into()
                }
            );
            println!(
                "🧠 Memory:         {} (auto-save: {})",
                effective_memory_backend,
                if config.memory.auto_save { "on" } else { "off" }
            );

            println!();
            println!("Security:");
            println!("  Workspace only:    {}", config.autonomy.workspace_only);
            println!(
                "  Allowed roots:     {}",
                if config.autonomy.allowed_roots.is_empty() {
                    "(none)".to_string()
                } else {
                    config.autonomy.allowed_roots.join(", ")
                }
            );
            println!(
                "  Allowed commands:  {}",
                config.autonomy.allowed_commands.join(", ")
            );
            println!(
                "  Max actions/hour:  {}",
                config.autonomy.max_actions_per_hour
            );
            println!(
                "  Max cost/day:      ${:.2}",
                f64::from(config.autonomy.max_cost_per_day_cents) / 100.0
            );
            println!("  OTP enabled:       {}", config.security.otp.enabled);
            println!("  E-stop enabled:    {}", config.security.estop.enabled);
            println!();
            println!("Channels:");
            println!("  CLI:      ✅ always");
            for (channel, configured) in config.channels_config.channels() {
                println!(
                    "  {:9} {}",
                    channel.name(),
                    if configured {
                        "✅ configured"
                    } else {
                        "❌ not configured"
                    }
                );
            }
            println!();
            println!("Peripherals:");
            println!(
                "  Enabled:   {}",
                if config.peripherals.enabled {
                    "yes"
                } else {
                    "no"
                }
            );
            println!("  Boards:    {}", config.peripherals.boards.len());

            Ok(())
        }

        Commands::Estop {
            estop_command,
            level,
            domains,
            tools,
        } => handle_estop_command(&config, estop_command, level, domains, tools),

        Commands::Cron { cron_command } => cron::handle_command(cron_command, &config),

        Commands::Models { model_command } => match model_command {
            ModelCommands::Refresh {
                provider,
                all,
                force,
            } => {
                if all {
                    if provider.is_some() {
                        bail!("`models refresh --all` cannot be combined with --provider");
                    }
                    onboard::run_models_refresh_all(&config, force).await
                } else {
                    onboard::run_models_refresh(&config, provider.as_deref(), force).await
                }
            }
            ModelCommands::List { provider } => {
                onboard::run_models_list(&config, provider.as_deref()).await
            }
            ModelCommands::Set { model } => {
                Box::pin(onboard::run_models_set(&config, &model)).await
            }
            ModelCommands::Status => onboard::run_models_status(&config).await,
        },

        Commands::Providers => {
            let providers = providers::list_providers();
            let current = config
                .default_provider
                .as_deref()
                .unwrap_or("openrouter")
                .trim()
                .to_ascii_lowercase();
            println!("Supported providers ({} total):\n", providers.len());
            println!("  ID (use in config)  DESCRIPTION");
            println!("  ─────────────────── ───────────");
            for p in &providers {
                let is_active = p.name.eq_ignore_ascii_case(&current)
                    || p.aliases
                        .iter()
                        .any(|alias| alias.eq_ignore_ascii_case(&current));
                let marker = if is_active { " (active)" } else { "" };
                let local_tag = if p.local { " [local]" } else { "" };
                let aliases = if p.aliases.is_empty() {
                    String::new()
                } else {
                    format!("  (aliases: {})", p.aliases.join(", "))
                };
                println!(
                    "  {:<19} {}{}{}{}",
                    p.name, p.display_name, local_tag, marker, aliases
                );
            }
            println!("\n  custom:<URL>   Any OpenAI-compatible endpoint");
            println!("  anthropic-custom:<URL>  Any Anthropic-compatible endpoint");
            Ok(())
        }

        Commands::Service {
            service_command,
            service_init,
        } => {
            let init_system = service_init.parse()?;
            service::handle_command(&service_command, &config, init_system)
        }

        Commands::Doctor { doctor_command } => match doctor_command {
            Some(DoctorCommands::Models {
                provider,
                use_cache,
            }) => doctor::run_models(&config, provider.as_deref(), use_cache).await,
            Some(DoctorCommands::Traces {
                id,
                event,
                contains,
                limit,
            }) => doctor::run_traces(
                &config,
                id.as_deref(),
                event.as_deref(),
                contains.as_deref(),
                limit,
            ),
            None => doctor::run(&config),
        },

        Commands::Channel { channel_command } => match channel_command {
            ChannelCommands::Start => Box::pin(channels::start_channels(config)).await,
            ChannelCommands::Doctor => Box::pin(channels::doctor_channels(config)).await,
            other => Box::pin(channels::handle_command(other, &config)).await,
        },

        Commands::Integrations {
            integration_command,
        } => integrations::handle_command(integration_command, &config),

        Commands::Skills { skill_command } => skills::handle_command(skill_command, &config),

        Commands::Migrate { migrate_command } => {
            migration::handle_command(migrate_command, &config).await
        }

        Commands::Memory { memory_command } => {
            memory::cli::handle_command(memory_command, &config).await
        }

        Commands::Auth { auth_command } => handle_auth_command(auth_command, &config).await,

        Commands::Hardware { hardware_command } => {
            hardware::handle_command(hardware_command.clone(), &config)
        }

        Commands::Peripheral { peripheral_command } => {
            Box::pin(peripherals::handle_command(
                peripheral_command.clone(),
                &config,
            ))
            .await
        }

        Commands::Update {
            check,
            force,
            version,
        } => {
            if check {
                let info = commands::update::check(version.as_deref()).await?;
                if info.is_newer {
                    println!(
                        "Update available: v{} -> v{}",
                        info.current_version, info.latest_version
                    );
                } else {
                    println!("Already up to date (v{}).", info.current_version);
                }
                Ok(())
            } else {
                if !confirm_update(force)? {
                    println!("Update cancelled.");
                    return Ok(());
                }
                commands::update::run(version.as_deref()).await
            }
        }

        Commands::SelfTest { quick } => {
            let results = if quick {
                commands::self_test::run_quick(&config).await?
            } else {
                commands::self_test::run_full(&config).await?
            };
            commands::self_test::print_results(&results);
            let failed = results.iter().filter(|r| !r.passed).count();
            if failed > 0 {
                std::process::exit(1);
            }
            Ok(())
        }

        Commands::Config { config_command } => match config_command {
            ConfigCommands::Schema => {
                let schema = schemars::schema_for!(config::Config);
                println!(
                    "{}",
                    serde_json::to_string_pretty(&schema).expect("failed to serialize JSON Schema")
                );
                Ok(())
            }
        },

        #[cfg(feature = "plugins-wasm")]
        Commands::Plugin { plugin_command } => match plugin_command {
            PluginCommands::List => {
                let host = rain_labs::plugins::host::PluginHost::new(&config.workspace_dir)?;
                let plugins = host.list_plugins();
                if plugins.is_empty() {
                    println!("No plugins installed.");
                } else {
                    println!("Installed plugins:");
                    for p in &plugins {
                        println!(
                            "  {} v{} — {}",
                            p.name,
                            p.version,
                            p.description.as_deref().unwrap_or("(no description)")
                        );
                    }
                }
                Ok(())
            }
            PluginCommands::Install { source } => {
                let mut host = rain_labs::plugins::host::PluginHost::new(&config.workspace_dir)?;
                host.install_with_policy(
                    &source,
                    config.plugins.marketplace_enabled,
                    &config.plugins.allowed_permissions,
                )?;
                println!("Plugin installed from {source}");
                Ok(())
            }
            PluginCommands::Remove { name } => {
                let mut host = rain_labs::plugins::host::PluginHost::new(&config.workspace_dir)?;
                host.remove(&name)?;
                println!("Plugin '{name}' removed.");
                Ok(())
            }
            PluginCommands::Info { name } => {
                let host = rain_labs::plugins::host::PluginHost::new(&config.workspace_dir)?;
                match host.get_plugin(&name) {
                    Some(info) => {
                        println!("Plugin: {} v{}", info.name, info.version);
                        if let Some(desc) = &info.description {
                            println!("Description: {desc}");
                        }
                        println!("Capabilities: {:?}", info.capabilities);
                        println!("Permissions: {:?}", info.permissions);
                        println!("WASM: {}", info.wasm_path.display());
                    }
                    None => println!("Plugin '{name}' not found."),
                }
                Ok(())
            }
        },
    }
}
