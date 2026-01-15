// Original Copyright (c) 2022 Giovanni Barillari
// Modified by Velo Team for Velo Runtime, 2026
// SPDX-License-Identifier: BSD-3-Clause
//
// This file has been modified from the original Granian source.
// See vendor/granian/VENDOR.md for modification details.

// Allocator globals removed - Velo uses its own allocator strategy

use pyo3::prelude::*;
use std::sync::OnceLock;

// Core modules - made public for Velo integration
pub mod asgi;
pub mod asyncio;
pub mod blocking;
pub mod callbacks;
pub mod conversion;
pub mod files;
pub mod http;
pub mod net;
pub mod rsgi;
pub mod runtime;
pub mod sys;
pub mod tls;
pub mod utils;
pub mod workers;
pub mod ws;
pub mod wsgi;

#[cfg(not(Py_GIL_DISABLED))]
pub const BUILD_GIL: bool = true;
#[cfg(Py_GIL_DISABLED)]
pub const BUILD_GIL: bool = false;

pub fn get_granian_version() -> &'static str {
    static GRANIAN_VERSION: OnceLock<String> = OnceLock::new();

    GRANIAN_VERSION.get_or_init(|| {
        let version = env!("CARGO_PKG_VERSION");
        version.replace("-alpha", "a").replace("-beta", "b")
    })
}

// PyModule initialization remains for potential Python extension use
#[pymodule(gil_used = false)]
fn _granian(py: Python, module: &Bound<PyModule>) -> PyResult<()> {
    module.add("__version__", get_granian_version())?;
    module.add("BUILD_GIL", BUILD_GIL)?;
    module.add_class::<callbacks::CallbackScheduler>()?;
    asgi::init_pymodule(module)?;
    rsgi::init_pymodule(py, module)?;
    sys::init_pymodule(module)?;
    net::init_pymodule(module)?;
    workers::init_pymodule(module)?;
    wsgi::init_pymodule(module)?;
    Ok(())
}
