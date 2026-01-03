#[cfg(test)]
mod integration_tests {
    use anyhow::Result;
    use std::fs::{self, File};
    use std::io::Write;
    use tempfile::TempDir;

    use velo::cmd::bundle::{cmd_bundle_build, cmd_bundle_inspect, read_bundle_info};

    #[test]
    fn test_bundle_build_interactive() -> Result<()> {
        // Setup temp project
        let tmp_dir = TempDir::new()?;
        let project_root = tmp_dir.path().join("myproject");
        fs::create_dir(&project_root)?;

        // Create main.py
        let main_py = project_root.join("main.py");
        let mut f = File::create(&main_py)?;
        f.write_all(b"print('Hello Velo')")?;

        // Create package
        let pkg_dir = project_root.join("pkg");
        fs::create_dir(&pkg_dir)?;
        let init_py = pkg_dir.join("__init__.py");
        File::create(&init_py)?.write_all(b"x = 1")?;

        let output_bundle = tmp_dir.path().join("output.veloc");

        // Run build command
        let args = vec![
            "velo".to_string(),
            "bundle".to_string(),
            "build".to_string(),
            project_root.to_string_lossy().to_string(),
            output_bundle.to_string_lossy().to_string(),
        ];

        cmd_bundle_build(&args)?;

        assert!(output_bundle.exists());
        assert!(output_bundle.metadata()?.len() > 128); // Header + something

        // Inspect it to verify content
        let inspect_args = vec![
            "velo".to_string(),
            "bundle".to_string(),
            "inspect".to_string(),
            output_bundle.to_string_lossy().to_string(),
            "--verify".to_string(),
        ];

        // This prints to stdout, so we just check it doesn't fail
        cmd_bundle_inspect(&inspect_args)?;

        // Verify Graph section is present
        let info = read_bundle_info(&output_bundle)?;
        assert!(info.graph_offset > 0);
        assert_eq!(info.graph_offset % 4096, 0, "Graph must be 4KB aligned");

        Ok(())
    }
}
