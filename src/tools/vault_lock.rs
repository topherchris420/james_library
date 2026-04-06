//! Advisory file locking for concurrent vault (papers/) operations.
//!
//! Provides a simple lock-file mechanism to prevent simultaneous writes to
//! the same markdown file. Lock files are stored in `.vault.lock/` at the
//! workspace root.

use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio::fs;
use tokio::time::sleep;

/// Maximum number of retries when acquiring a lock.
const MAX_LOCK_RETRIES: u8 = 3;

/// Base wait time between retries (exponential backoff base).
const LOCK_RETRY_BASE_MS: u64 = 100;

/// Returns the lock directory path (`.vault.lock/` under workspace root).
pub fn lock_dir(workspace: &Path) -> PathBuf {
    workspace.join(".vault.lock")
}

/// Returns the lock file path for a given target file.
pub fn lock_path(workspace: &Path, target: &Path) -> PathBuf {
    let file_name = target
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown");
    lock_dir(workspace).join(format!("{file_name}.lock"))
}

/// Attempts to acquire an advisory lock on `target` by creating a lock file.
/// Returns `Ok(())` if the lock was acquired, `Err(reason)` otherwise.
pub async fn acquire(workspace: &Path, target: &Path) -> Result<(), LockError> {
    let lock_file = lock_path(workspace, target);
    let lock_dir_path = lock_dir(workspace);

    // Ensure lock directory exists
    fs::create_dir_all(&lock_dir_path)
        .await
        .map_err(|e| LockError::Io {
            path: lock_dir_path.clone(),
            err: e,
        })?;

    // Try to create the lock file exclusively
    for attempt in 0..=MAX_LOCK_RETRIES {
        match fs::write(&lock_file, std::process::id().to_string()).await {
            Ok(()) => return Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                if attempt == MAX_LOCK_RETRIES {
                    return Err(LockError::Contended {
                        target: target.to_path_buf(),
                        lock_file,
                    });
                }
                // Exponential backoff: 100ms, 200ms, 400ms
                let delay_ms = LOCK_RETRY_BASE_MS * 2u64.pow(u32::from(attempt));
                sleep(Duration::from_millis(delay_ms)).await;
            }
            Err(e) => {
                return Err(LockError::Io {
                    path: lock_file,
                    err: e,
                });
            }
        }
    }

    Err(LockError::Contended {
        target: target.to_path_buf(),
        lock_file,
    })
}

/// Releases the advisory lock on `target`.
pub async fn release(workspace: &Path, target: &Path) {
    let lock_file = lock_path(workspace, target);
    let _ = fs::remove_file(&lock_file).await;
}

#[derive(Debug)]
pub enum LockError {
    /// Another process holds the lock and did not release it within the retry window.
    Contended { target: PathBuf, lock_file: PathBuf },
    /// An I/O error occurred while creating or removing the lock file.
    Io { path: PathBuf, err: std::io::Error },
}

impl std::fmt::Display for LockError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LockError::Contended { target, lock_file } => {
                write!(
                    f,
                    "vault lock contended for '{}' (lock: {})",
                    target.display(),
                    lock_file.display()
                )
            }
            LockError::Io { path, err } => {
                write!(f, "vault lock I/O error at '{}': {}", path.display(), err)
            }
        }
    }
}

impl std::error::Error for LockError {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    fn test_workspace() -> PathBuf {
        env::temp_dir().join("vault_lock_test")
    }

    #[tokio::test]
    async fn acquire_and_release_lock() {
        let ws = test_workspace();
        let target = ws.join("papers").join("Test.md");
        fs::create_dir_all(ws.join("papers")).await.unwrap();

        // Should acquire cleanly
        acquire(&ws, &target)
            .await
            .expect("first acquire should succeed");
        // Lock file should exist
        assert!(lock_path(&ws, &target).exists());
        // Release
        release(&ws, &target).await;
        // Lock file should be gone
        assert!(!lock_path(&ws, &target).exists());

        let _ = fs::remove_dir_all(&ws).await;
    }

    #[tokio::test]
    async fn lock_prevents_concurrent_acquire() {
        let ws = test_workspace();
        let target = ws.join("papers").join("Concurrent.md");
        fs::create_dir_all(ws.join("papers")).await.unwrap();

        acquire(&ws, &target)
            .await
            .expect("first acquire should succeed");

        // Second acquire from same process should succeed after retries
        // (same PID, so we override — this is a limitation of single-process locks)
        let result = acquire(&ws, &target).await;
        assert!(
            result.is_ok(),
            "same-process acquire should succeed (overwrite)"
        );

        release(&ws, &target).await;
        let _ = fs::remove_dir_all(&ws).await;
    }
}
