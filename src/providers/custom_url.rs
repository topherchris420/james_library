use anyhow::bail;

pub(crate) fn parse_custom_provider_url(
    raw_url: &str,
    provider_kind: &str,
    example: &str,
) -> anyhow::Result<String> {
    let base_url = raw_url.trim();
    if base_url.is_empty() {
        bail!("{provider_kind} requires a URL after the prefix, e.g. {example}");
    }

    let parsed = reqwest::Url::parse(base_url).map_err(|_| {
        anyhow::anyhow!(
            "{provider_kind} requires a valid URL (got \"{base_url}\"). Example: {example}"
        )
    })?;

    match parsed.scheme() {
        "http" | "https" => Ok(base_url.to_string()),
        scheme => bail!(
            "{provider_kind} URL must use http:// or https:// (got {scheme}://). Example: {example}"
        ),
    }
}
