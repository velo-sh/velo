pub mod paths;

// Import generated constants from OUT_DIR
pub mod constants {
    include!(concat!(env!("OUT_DIR"), "/constants.rs"));
}
