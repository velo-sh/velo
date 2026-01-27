//! Zygote CLI argument parsing

use std::path::PathBuf;

/// Parsed zygote-related arguments
#[derive(Debug, Default)]
pub struct ZygoteArgs {
    /// Whether --zygote flag was specified
    pub zygote_enabled: bool,
    /// Script path to run
    pub script_path: Option<PathBuf>,
    /// Additional arguments to pass to script
    pub script_args: Vec<String>,
    /// Modules to preload
    pub preload: Vec<String>,
}

/// Parse zygote-related arguments from command line
pub fn parse_zygote_args(args: &[&str]) -> ZygoteArgs {
    let mut result = ZygoteArgs::default();

    let mut i = 0;
    while i < args.len() {
        match args[i] {
            "--zygote" => {
                result.zygote_enabled = true;
            }
            "--preload" if i + 1 < args.len() => {
                i += 1;
                result.preload = args[i].split(',').map(|s| s.to_string()).collect();
            }
            arg if arg.ends_with(".py") => {
                result.script_path = Some(PathBuf::from(arg));
                // Remaining args are script args
                result.script_args = args[i + 1..].iter().map(|s| s.to_string()).collect();
                break;
            }
            _ => {}
        }
        i += 1;
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_with_zygote_flag() {
        let args = vec!["velo", "run", "--zygote", "script.py"];
        let parsed = parse_zygote_args(&args);
        assert!(parsed.zygote_enabled);
        assert_eq!(parsed.script_path, Some(PathBuf::from("script.py")));
    }

    #[test]
    fn test_parse_without_zygote_flag() {
        let args = vec!["velo", "run", "script.py"];
        let parsed = parse_zygote_args(&args);
        assert!(!parsed.zygote_enabled);
        assert_eq!(parsed.script_path, Some(PathBuf::from("script.py")));
    }

    #[test]
    fn test_parse_with_preload() {
        let args = vec![
            "velo",
            "run",
            "--zygote",
            "--preload",
            "numpy,pandas",
            "script.py",
        ];
        let parsed = parse_zygote_args(&args);
        assert!(parsed.zygote_enabled);
        assert_eq!(parsed.preload, vec!["numpy", "pandas"]);
    }
}
