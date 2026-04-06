use super::{
    GLM_CN_BASE_URL, GLM_GLOBAL_BASE_URL, MINIMAX_CN_BASE_URL, MINIMAX_INTL_BASE_URL,
    MOONSHOT_CN_BASE_URL, MOONSHOT_INTL_BASE_URL, QWEN_CN_BASE_URL, QWEN_INTL_BASE_URL,
    QWEN_US_BASE_URL, ZAI_CN_BASE_URL, ZAI_GLOBAL_BASE_URL, is_glm_cn_alias, is_glm_global_alias,
    is_minimax_cn_alias, is_minimax_intl_alias, is_moonshot_cn_alias, is_moonshot_intl_alias,
    is_qwen_cn_alias, is_qwen_intl_alias, is_qwen_oauth_alias, is_qwen_us_alias, is_zai_cn_alias,
    is_zai_global_alias,
};

pub(super) fn minimax_base_url(name: &str) -> Option<&'static str> {
    if is_minimax_cn_alias(name) {
        Some(MINIMAX_CN_BASE_URL)
    } else if is_minimax_intl_alias(name) {
        Some(MINIMAX_INTL_BASE_URL)
    } else {
        None
    }
}

pub(super) fn glm_base_url(name: &str) -> Option<&'static str> {
    if is_glm_cn_alias(name) {
        Some(GLM_CN_BASE_URL)
    } else if is_glm_global_alias(name) {
        Some(GLM_GLOBAL_BASE_URL)
    } else {
        None
    }
}

pub(super) fn moonshot_base_url(name: &str) -> Option<&'static str> {
    if is_moonshot_intl_alias(name) {
        Some(MOONSHOT_INTL_BASE_URL)
    } else if is_moonshot_cn_alias(name) {
        Some(MOONSHOT_CN_BASE_URL)
    } else {
        None
    }
}

pub(super) fn qwen_base_url(name: &str) -> Option<&'static str> {
    if is_qwen_cn_alias(name) || is_qwen_oauth_alias(name) {
        Some(QWEN_CN_BASE_URL)
    } else if is_qwen_intl_alias(name) {
        Some(QWEN_INTL_BASE_URL)
    } else if is_qwen_us_alias(name) {
        Some(QWEN_US_BASE_URL)
    } else {
        None
    }
}

pub(super) fn zai_base_url(name: &str) -> Option<&'static str> {
    if is_zai_cn_alias(name) {
        Some(ZAI_CN_BASE_URL)
    } else if is_zai_global_alias(name) {
        Some(ZAI_GLOBAL_BASE_URL)
    } else {
        None
    }
}
