//! Terminal UI components for interactive onboarding and status display.
//!
//! Uses ratatui + crossterm for rich terminal interfaces. The TUI onboarding
//! flow is an alternative to the CLI-prompt-based `onboard` wizard.

pub mod onboarding;
mod theme;
mod widgets;
