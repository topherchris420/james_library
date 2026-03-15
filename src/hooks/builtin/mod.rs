pub mod command_logger;
pub mod episodic_memory;

pub use command_logger::CommandLoggerHook;
// EpisodicMemoryHook is part of the crate's public hook API surface.
// It may appear unused internally but is intentionally re-exported for
// runtime registration by agent builders and external integrations.
#[allow(unused_imports)]
pub use episodic_memory::EpisodicMemoryHook;
