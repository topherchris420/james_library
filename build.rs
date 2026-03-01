use std::fs;
use std::path::Path;

const PLACEHOLDER_INDEX_HTML: &str = r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ZeroClaw Dashboard</title>
</head>
<body>
  <div id="app">Dashboard assets are not built yet. Run the web build to replace this placeholder.</div>
</body>
</html>
"#;

fn main() {
    let dist_dir = Path::new("web").join("dist");
    let index_path = dist_dir.join("index.html");

    if !dist_dir.exists() {
        fs::create_dir_all(&dist_dir).expect("failed to create web/dist");
    }

    if !index_path.exists() {
        fs::write(&index_path, PLACEHOLDER_INDEX_HTML).expect("failed to write web/dist/index.html");
    }

    println!("cargo:rerun-if-changed=web/dist");
}
