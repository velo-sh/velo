use std::process::Command;

#[test]
fn test_pyo3_feature_leakage_audit() {
    // Audit for SSoT: We must ensure 'extension-module' is NOT activated for the velo binary
    // This systematically prevents the linker errors we saw on macOS/CI.

    let output = Command::new("cargo")
        .args(["metadata", "--format-version", "1"])
        .output()
        .expect("Failed to execute cargo metadata");

    assert!(output.status.success(), "cargo metadata failed");

    let json: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("Failed to parse cargo metadata JSON");

    // Find pyo3 package in the resolved dependency graph
    let resolve = json.get("resolve").expect("Missing resolve section");
    let nodes = resolve
        .get("nodes")
        .expect("Missing nodes in resolve")
        .as_array()
        .expect("Nodes not an array");

    let pyo3_node = nodes.iter().find(|n| {
        n.get("id")
            .and_then(|id| id.as_str())
            .map(|id| id.contains("pyo3 "))
            .unwrap_or(false)
    });

    if let Some(node) = pyo3_node {
        let features = node
            .get("features")
            .and_then(|f| f.as_array())
            .expect("Features not an array");
        let has_extension_module = features
            .iter()
            .any(|f| f.as_str() == Some("extension-module"));

        if has_extension_module {
            panic!(
                "\n\n[AUDIT FAILURE] 'extension-module' feature leaked into pyo3 dependency!\n\
                   This will cause linker errors for the embedded velo binary.\n\
                   Check all dependencies (including vendor/) and ensure NONE of them set 'extension-module'.\n\n"
            );
        }
    }
}
