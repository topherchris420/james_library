//! TUI-based onboarding wizard.
//!
//! Provides a rich terminal interface for first-time setup as an alternative
//! to the CLI-prompt-based wizard.

use anyhow::Result;

/// Run the TUI onboarding flow.
///
/// This is an alternative to the CLI-prompt-based `onboard` wizard that
/// provides a richer interactive experience with visual feedback.
///
/// Returns `Ok(())` on successful completion, or an error if the user
/// cancels or the terminal is not interactive.
pub fn run_tui_onboarding() -> Result<()> {
    // TUI onboarding is a progressive enhancement — fall back to CLI wizard
    // if the terminal doesn't support the required capabilities.
    if !std::io::IsTerminal::is_terminal(&std::io::stdout()) {
        anyhow::bail!("TUI onboarding requires an interactive terminal");
    }

    tracing::info!("TUI onboarding: placeholder — use `rain onboard` for the CLI wizard");
    Ok(())
}
