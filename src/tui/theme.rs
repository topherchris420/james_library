//! TUI color theme and styling constants.

use ratatui::style::{Color, Modifier, Style};

/// Primary accent color.
pub const ACCENT: Color = Color::Cyan;

/// Success indicator color.
pub const SUCCESS: Color = Color::Green;

/// Warning indicator color.
pub const WARNING: Color = Color::Yellow;

/// Error indicator color.
pub const ERROR: Color = Color::Red;

/// Dimmed/secondary text color.
pub const DIM: Color = Color::DarkGray;

/// Default text style.
pub fn text() -> Style {
    Style::default()
}

/// Bold text style.
pub fn bold() -> Style {
    Style::default().add_modifier(Modifier::BOLD)
}

/// Accent-colored bold text.
pub fn accent() -> Style {
    Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
}

/// Dimmed text for secondary information.
pub fn dim() -> Style {
    Style::default().fg(DIM)
}
