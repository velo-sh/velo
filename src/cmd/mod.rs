//! CLI command dispatch module
//!
//! Organizes commands into separate files for maintainability.

pub mod analyze;
pub mod bench;
pub mod bundle;
pub mod graph;
pub mod info;
pub mod run;
pub mod serve;
pub mod zygote;

pub use analyze::cmd_analyze;
pub use bench::cmd_bench;
pub use bundle::cmd_bundle;
pub use graph::cmd_graph;
pub use info::cmd_info;
pub use run::cmd_run;
pub use serve::cmd_serve;
pub use zygote::cmd_zygote;
