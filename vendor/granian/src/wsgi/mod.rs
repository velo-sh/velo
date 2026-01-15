mod callbacks;
mod http;
mod io;
pub mod serve;
mod types;

use pyo3::prelude::*;

pub fn init_pymodule(module: &Bound<PyModule>) -> PyResult<()> {
    module.add_class::<io::WSGIProtocol>()?;
    module.add_class::<io::WSGIWrite>()?;
    module.add_class::<types::WSGIBody>()?;
    module.add_class::<serve::WSGIWorker>()?;
    Ok(())
}
