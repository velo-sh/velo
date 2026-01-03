#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TargetArch {
    Unknown = 0,
    X86_64 = 1,
    Aarch64 = 2,
}

impl TargetArch {
    pub fn current() -> Self {
        #[cfg(target_arch = "x86_64")]
        {
            TargetArch::X86_64
        }
        #[cfg(target_arch = "aarch64")]
        {
            TargetArch::Aarch64
        }
        #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
        {
            TargetArch::Unknown
        }
    }
}

pub mod builder;
pub mod cycle;
pub mod dependency;
pub mod metrics;
pub mod serializer;

pub use metrics::report_metrics;
