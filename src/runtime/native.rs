use super::traits::RuntimeAdapter;
use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// Native runtime — full access, runs on Mac/Linux/Docker/Raspberry Pi
pub struct NativeRuntime;

impl NativeRuntime {
    pub fn new() -> Self {
        Self
    }
}

impl RuntimeAdapter for NativeRuntime {
    fn name(&self) -> &str {
        "native"
    }

    fn has_shell_access(&self) -> bool {
        true
    }

    fn has_filesystem_access(&self) -> bool {
        true
    }

    fn storage_path(&self) -> PathBuf {
        directories::UserDirs::new().map_or_else(
            || PathBuf::from(".zeroclaw"),
            |u| u.home_dir().join(".zeroclaw"),
        )
    }

    fn supports_long_running(&self) -> bool {
        true
    }

    fn build_shell_command(
        &self,
        command: &str,
        workspace_dir: &Path,
    ) -> anyhow::Result<tokio::process::Command> {
        #[cfg(windows)]
        let mut process = {
            let shell = std::env::var_os("COMSPEC").unwrap_or_else(|| OsString::from("cmd.exe"));
            let mut process = tokio::process::Command::new(shell);
            // Pass all environment variables to ensure PATH, TEMP, etc. are available
            process.envs(std::env::vars());
            process.arg("/d").arg("/s").arg("/c").arg(command);
            process
        };

        #[cfg(not(windows))]
        let mut process = {
            let mut process = tokio::process::Command::new("sh");
            // Pass all environment variables for cross-platform compatibility
            process.envs(std::env::vars());
            process.arg("-c").arg(command);
            process
        };

        process.current_dir(workspace_dir);
        Ok(process)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_name() {
        assert_eq!(NativeRuntime::new().name(), "native");
    }

    #[test]
    fn native_has_shell_access() {
        assert!(NativeRuntime::new().has_shell_access());
    }

    #[test]
    fn native_has_filesystem_access() {
        assert!(NativeRuntime::new().has_filesystem_access());
    }

    #[test]
    fn native_supports_long_running() {
        assert!(NativeRuntime::new().supports_long_running());
    }

    #[test]
    fn native_memory_budget_unlimited() {
        assert_eq!(NativeRuntime::new().memory_budget(), 0);
    }

    #[test]
    fn native_storage_path_contains_zeroclaw() {
        let path = NativeRuntime::new().storage_path();
        assert!(path.to_string_lossy().contains("zeroclaw"));
    }

    #[test]
    fn native_builds_shell_command() {
        let cwd = std::env::temp_dir();
        let command = NativeRuntime::new()
            .build_shell_command("echo hello", &cwd)
            .unwrap();
        let debug = format!("{command:?}");
        assert!(debug.contains("echo hello"));
    }

    #[cfg(windows)]
    #[test]
    fn native_windows_uses_cmd_shell() {
        let cwd = std::env::temp_dir();
        let command = NativeRuntime::new()
            .build_shell_command("dir", &cwd)
            .unwrap();
        let debug = format!("{command:?}").to_ascii_lowercase();
        assert!(debug.contains("cmd"));
        assert!(debug.contains("/c"));
    }

    #[cfg(not(windows))]
    #[test]
    fn native_unix_uses_sh_shell() {
        let cwd = std::env::temp_dir();
        let command = NativeRuntime::new()
            .build_shell_command("echo hello", &cwd)
            .unwrap();
        let debug = format!("{command:?}");
        assert!(debug.contains("sh"));
        assert!(debug.contains("-c"));
    }
}
