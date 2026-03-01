# Binary Releases

Prebuilt binaries are published through `.github/workflows/pub-release.yml`.

## Where to download

- GitHub Releases page:
  - https://github.com/topherchris420/james_library/releases

## Available targets

- `x86_64-unknown-linux-gnu`
- `aarch64-unknown-linux-gnu`
- `armv7-unknown-linux-gnueabihf`
- `x86_64-apple-darwin`
- `aarch64-apple-darwin`
- `x86_64-pc-windows-msvc`

## Artifact names

- Linux/macOS: `zeroclaw-<target>.tar.gz`
- Windows: `zeroclaw-<target>.zip`

Example:

- `zeroclaw-x86_64-pc-windows-msvc.zip`

## Verify and run

Linux/macOS:

```bash
tar -xzf zeroclaw-x86_64-unknown-linux-gnu.tar.gz
./zeroclaw --help
```

Windows PowerShell:

```powershell
Expand-Archive .\zeroclaw-x86_64-pc-windows-msvc.zip -DestinationPath .\zeroclaw-bin
.\zeroclaw-bin\zeroclaw.exe --help
```
