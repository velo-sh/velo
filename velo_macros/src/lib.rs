use proc_macro::TokenStream;
use quote::quote;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[proc_macro]
pub fn generate_config(_input: TokenStream) -> TokenStream {
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| ".".to_string());
    let mut toml_path = Path::new(&manifest_dir).join("config/constants.toml");

    if !toml_path.exists() {
        toml_path = Path::new(&manifest_dir).join("../config/constants.toml");
    }

    if !toml_path.exists() {
        toml_path = Path::new(&manifest_dir).join("../../config/constants.toml");
    }

    if !toml_path.exists() {
        return TokenStream::from(quote! {
            compile_error!("Could not find config/constants.toml");
        });
    }

    let toml_content = fs::read_to_string(&toml_path).expect("Failed to read TOML");
    let config: HashMap<String, serde_json::Value> =
        toml::from_str(&toml_content).expect("Failed to parse TOML");

    let get_str = |key: &str, default: &str| {
        config
            .get(key)
            .and_then(|v: &serde_json::Value| v.as_str())
            .unwrap_or(default)
            .to_string()
    };

    let get_u64 = |key: &str, default: u64| {
        config
            .get(key)
            .and_then(|v: &serde_json::Value| v.as_i64())
            .unwrap_or(default as i64) as u64
    };

    let get_bool = |key: &str, default: bool| {
        config
            .get(key)
            .and_then(|v: &serde_json::Value| v.as_bool())
            .unwrap_or(default)
    };

    // Basic constants
    let socket_timeout = get_u64("socket_startup_timeout", 30);
    let slow_threshold = get_u64("default_slow_threshold_ms", 100);
    let slo_fork_latency = get_u64("slo_fork_latency_ms", 100);
    let shutdown_timeout = get_u64("graceful_shutdown_timeout", 30);
    let hpc_threads = get_u64("security_hpc_threads", 1) as usize;
    let path_integrity = get_str("path_integrity", "warn");
    let strict_opt = get_bool("strict_optimizations", true);
    let cb_threshold = get_u64("circuit_breaker_threshold", 3);
    let cb_enabled = get_bool("circuit_breaker_enabled", true);
    let metrics_enabled = get_bool("metrics_enabled", true);
    let tracing_enabled = get_bool("tracing_enabled", true);
    let auto_sync = get_bool("auto_sync_enabled", true);
    let zygote_pool_size = get_u64("zygote_pool_size", 0) as usize;
    let blocked_paths = config
        .get("default_blocked_paths")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect::<Vec<String>>()
        })
        .unwrap_or_default();

    // Security Matrix (Baked-in defaults)
    let base_prefixes = get_str("security_base_trusted_prefixes", "");
    let macos_base_prefixes =
        get_str("security_macos_base_trusted_prefixes", "").replace("${BASE}", &base_prefixes);
    let macos_dev_prefixes = get_str("security_macos_dev_trusted_prefixes", "")
        .replace("${OS_BASE}", &macos_base_prefixes);
    let macos_ci_prefixes = get_str("security_macos_ci_trusted_prefixes", "")
        .replace("${OS_BASE}", &macos_base_prefixes);
    let macos_prod_prefixes = get_str("security_macos_prod_trusted_prefixes", "")
        .replace("${OS_BASE}", &macos_base_prefixes);

    let linux_base_prefixes =
        get_str("security_linux_base_trusted_prefixes", "").replace("${BASE}", &base_prefixes);
    let linux_dev_prefixes = get_str("security_linux_dev_trusted_prefixes", "")
        .replace("${OS_BASE}", &linux_base_prefixes);
    let linux_ci_prefixes = get_str("security_linux_ci_trusted_prefixes", "")
        .replace("${OS_BASE}", &linux_base_prefixes);
    let linux_prod_prefixes = get_str("security_linux_prod_trusted_prefixes", "")
        .replace("${OS_BASE}", &linux_base_prefixes);

    // Environment Whitelist (Baked-in defaults)
    let base_envs = get_str("security_base_env_whitelist", "");
    let macos_base_envs =
        get_str("security_macos_base_env_whitelist", "").replace("${BASE}", &base_envs);
    let macos_dev_envs =
        get_str("security_macos_dev_env_whitelist", "").replace("${OS_BASE}", &macos_base_envs);
    let macos_ci_envs =
        get_str("security_macos_ci_env_whitelist", "").replace("${OS_BASE}", &macos_base_envs);
    let macos_prod_envs =
        get_str("security_macos_prod_env_whitelist", "").replace("${OS_BASE}", &macos_base_envs);

    let linux_base_envs =
        get_str("security_linux_base_env_whitelist", "").replace("${BASE}", &base_envs);
    let linux_dev_envs =
        get_str("security_linux_dev_env_whitelist", "").replace("${OS_BASE}", &linux_base_envs);
    let linux_ci_envs =
        get_str("security_linux_ci_env_whitelist", "").replace("${OS_BASE}", &linux_base_envs);
    let linux_prod_envs =
        get_str("security_linux_prod_env_whitelist", "").replace("${OS_BASE}", &linux_base_envs);

    let expanded = quote! {
        /// Velo configuration (Auto-generated from constants.toml)
        #[derive(Debug, Clone)]
        pub struct VeloConfig {
            pub preload: Vec<String>,
            pub native_libraries: Vec<String>,
            pub path_integrity: String,
            pub max_bundle_size: usize,
            pub zygote_socket_timeout: u64,
            pub slow_threshold_ms: u64,
            pub slo_fork_latency_ms: u64,
            pub security_trusted_prefixes: Vec<String>,
            pub security_env_whitelist: Vec<String>,
            pub security_hpc_threads: usize,
            pub graceful_shutdown_timeout: u64,
            pub strict_optimizations: bool,
            pub circuit_breaker_threshold: u32,
            pub circuit_breaker_enabled: bool,
            pub metrics_enabled: bool,
            pub tracing_enabled: bool,
            pub auto_sync_enabled: bool,
            pub zygote_pool_size: usize,
            pub forensic_secret: Option<String>,
            pub default_blocked_paths: Vec<String>,
        }

        impl Default for VeloConfig {
            fn default() -> Self {
                let env_mode = match std::env::var("VELO_ENV") {
                    Ok(mode) => mode,
                    Err(_) => {
                        if std::env::var("VELO_TEST_MODE").is_ok() {
                            "ci".to_string()
                        } else {
                            "dev".to_string()
                        }
                    }
                };

                let os_name = std::env::consts::OS;

                let (raw_prefixes, raw_envs) = match (os_name, env_mode.as_str()) {
                    ("macos", "prod") => (#macos_prod_prefixes, #macos_prod_envs),
                    ("macos", "ci") => (#macos_ci_prefixes, #macos_ci_envs),
                    ("macos", _) => (#macos_dev_prefixes, #macos_dev_envs),
                    ("linux", "prod") => (#linux_prod_prefixes, #linux_prod_envs),
                    ("linux", "ci") => (#linux_ci_prefixes, #linux_ci_envs),
                    ("linux", _) => (#linux_dev_prefixes, #linux_dev_envs),
                    _ => (#linux_dev_prefixes, #linux_dev_envs),
                };

                let blocked_paths_raw = vec![#(#blocked_paths),*];

                Self {
                    preload: Vec::new(),
                    native_libraries: Vec::new(),
                    path_integrity: #path_integrity.to_string(),
                    max_bundle_size: 1024 * 1024 * 1024,
                    zygote_socket_timeout: #socket_timeout,
                    slow_threshold_ms: #slow_threshold,
                    slo_fork_latency_ms: #slo_fork_latency,
                    security_trusted_prefixes: Self::parse_string_array(raw_prefixes),
                    security_env_whitelist: Self::parse_string_array(raw_envs),
                    security_hpc_threads: #hpc_threads,
                    graceful_shutdown_timeout: #shutdown_timeout,
                    strict_optimizations: match env_mode.as_str() {
                        "prod" => false,
                        "ci" => false,
                        _ => #strict_opt,
                    },
                    circuit_breaker_threshold: #cb_threshold as u32,
                    circuit_breaker_enabled: #cb_enabled,
                    metrics_enabled: #metrics_enabled,
                    tracing_enabled: #tracing_enabled,
                    auto_sync_enabled: #auto_sync,
                    zygote_pool_size: #zygote_pool_size,
                    forensic_secret: None,
                    default_blocked_paths: blocked_paths_raw.into_iter().map(|s| s.to_string()).collect(),
                }
            }
        }
    };

    TokenStream::from(expanded)
}
