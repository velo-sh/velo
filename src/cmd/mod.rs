//! CLI command dispatch module
//!
//! Organizes commands into separate files for maintainability.

pub mod analyze;
pub mod bench;
pub mod bundle;
pub mod debug;
pub mod graph;
pub mod info;
pub mod python;
pub mod run;
pub mod serve;
pub mod zygote; // RFC-0018: Shadow commands

pub use analyze::cmd_analyze;
pub use bench::cmd_bench;
pub use bundle::cmd_bundle;
pub use debug::cmd_debug;
pub use graph::cmd_graph;
pub use info::cmd_info;
pub use python::{cmd_pip, cmd_python}; // RFC-0018
pub use run::cmd_run;
pub use serve::cmd_serve;
pub use zygote::cmd_zygote;
