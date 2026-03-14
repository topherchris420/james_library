#[allow(clippy::module_inception)]
pub mod advisory;
pub mod agent;
pub mod classifier;
pub(crate) mod credentials;
pub mod dispatcher;
pub(crate) mod history;
pub mod loop_;
pub mod memory_loader;
pub mod prompt;
pub(crate) mod tool_call_parsing;
pub(crate) mod tool_execution;

#[cfg(test)]
mod tests;

#[allow(unused_imports)]
pub use agent::{Agent, AgentBuilder};
#[allow(unused_imports)]
pub use loop_::{process_message, run};
