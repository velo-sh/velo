//! CLI command dispatch module
//!
//! Organizes commands into separate files for maintainability.

pub mod analyze;
pub mod audit;
pub mod bench;
pub mod bundle;
pub mod debug;
pub mod graph;
pub mod info;
pub mod jupyter; // RFC-0030: Jupyter kernel integration
pub mod pre_flight;
pub mod preload;

pub mod python;
pub mod run;
pub mod serve;
pub mod vtest; // RFC-0028: Zygote-accelerated testing (velo test)
pub mod worker_native;
pub mod zygote; // RFC-0018: Shadow commands

pub use analyze::cmd_analyze;
pub use audit::cmd_audit;
pub use bench::cmd_bench;
pub use bundle::cmd_bundle;
pub use debug::cmd_debug;
pub use graph::cmd_graph;
pub use info::cmd_info;
pub use jupyter::cmd_jupyter; // RFC-0030: Jupyter kernel
pub use pre_flight::cmd_debug_pre_flight;
pub use preload::cmd_preload;
pub use python::cmd_python; // RFC-0018: managed Python
pub use run::cmd_run;
pub use serve::cmd_serve;
pub use vtest::cmd_vtest; // RFC-0028: `velo test` command
pub use worker_native::cmd_worker_native;
pub use zygote::cmd_zygote;
