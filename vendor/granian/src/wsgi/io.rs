use futures::StreamExt;
use http_body_util::BodyExt;
use hyper::{
    body,
    header::{HeaderMap, HeaderName, HeaderValue, SERVER as HK_SERVER},
};
use pyo3::{prelude::*, pybacked::PyBackedStr};
use std::{borrow::Cow, sync::Mutex};
use tokio::sync::{mpsc, oneshot};

use crate::{
    http::{HTTPResponseBody, HV_SERVER},
    utils::log_application_callable_exception,
};

// NOTE: for unknown reasons, under some circumstances (`threading` module usage in app?)
//       this gets shared across threads. So it can't be `unsendable` (yet?).
#[pyclass(frozen)]
pub(super) struct WSGIProtocol {
    tx: Mutex<Option<oneshot::Sender<(u16, HeaderMap, HTTPResponseBody)>>>,
    status: Mutex<Option<u16>>,
    headers: Mutex<Option<Vec<(PyBackedStr, PyBackedStr)>>>,
}

#[pyclass(frozen)]
pub(super) struct WSGIWrite;

#[pymethods]
impl WSGIWrite {
    fn __call__(&self, _data: Bound<PyAny>) {}
}

impl WSGIProtocol {
    pub fn new(tx: oneshot::Sender<(u16, HeaderMap, HTTPResponseBody)>) -> Self {
        Self {
            tx: Mutex::new(Some(tx)),
            status: Mutex::new(None),
            headers: Mutex::new(None),
        }
    }

    pub fn tx(&self) -> Option<oneshot::Sender<(u16, HeaderMap, HTTPResponseBody)>> {
        self.tx.lock().map_or(None, |mut v| v.take())
    }

    pub fn take_info(&self) -> Option<(u16, Vec<(PyBackedStr, PyBackedStr)>)> {
        let status = self.status.lock().unwrap().take();
        let headers = self.headers.lock().unwrap().take();
        if let (Some(status), Some(headers)) = (status, headers) {
            return Some((status, headers));
        }
        None
    }
}

macro_rules! headers_from_py {
    ($headers:expr) => {{
        let mut headers = HeaderMap::with_capacity($headers.len() + 3);
        for (key, value) in $headers {
            headers.append(
                HeaderName::from_bytes(key.as_bytes()).unwrap(),
                HeaderValue::from_str(&value).unwrap(),
            );
        }
        headers.entry(HK_SERVER).or_insert(HV_SERVER);
        headers
    }};
}

#[pymethods]
impl WSGIProtocol {
    pub(crate) fn response_bytes(
        &self,
        status: u16,
        headers: Vec<(PyBackedStr, PyBackedStr)>,
        body: Cow<[u8]>,
    ) {
        if let Some(tx) = self.tx.lock().map_or(None, |mut v| v.take()) {
            let data: Box<[u8]> = body.into();
            let txbody = http_body_util::Full::new(body::Bytes::from(data))
                .map_err(|e| match e {})
                .boxed();
            let _ = tx.send((status, headers_from_py!(headers), txbody));
        }
    }

    pub(crate) fn response_iter(
        &self,
        py: Python,
        status: u16,
        headers: Vec<(PyBackedStr, PyBackedStr)>,
        body: Bound<PyAny>,
    ) {
        if let Some(tx) = self.tx.lock().map_or(None, |mut v| v.take()) {
            let (body_tx, body_rx) = mpsc::unbounded_channel::<body::Bytes>();

            let body_stream = http_body_util::StreamBody::new(
                tokio_stream::wrappers::UnboundedReceiverStream::new(body_rx)
                    .map(body::Frame::data)
                    .map(Result::Ok),
            );
            let txbody = BodyExt::boxed(body_stream);
            let _ = tx.send((status, headers_from_py!(headers), txbody));

            let iter_res = body.as_any().call_method0(pyo3::intern!(py, "__iter__"));
            if let Ok(iterator) = iter_res {
                loop {
                    match iterator.call_method0(pyo3::intern!(py, "__next__")) {
                        Ok(chunk_obj) => {
                            let chunk: Cow<'_, [u8]> = match chunk_obj.extract() {
                                Ok(c) => c,
                                Err(_) => break,
                            };
                            let data: Box<[u8]> = chunk.into();
                            if body_tx.send(body::Bytes::from(data)).is_err() {
                                break;
                            }
                        }
                        Err(err) => {
                            if !err.is_instance_of::<pyo3::exceptions::PyStopIteration>(py) {
                                log_application_callable_exception(py, &err);
                            }
                            break;
                        }
                    }
                }
            }

            let _ = body.call_method0(pyo3::intern!(py, "close"));
        }
    }

    #[pyo3(signature = (status, headers, _exc_info=None))]
    fn __call__(
        &self,
        py: Python,
        status: String,
        headers: Vec<(PyBackedStr, PyBackedStr)>,
        _exc_info: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let status_code = status
            .split_whitespace()
            .next()
            .unwrap_or("200")
            .parse::<u16>()
            .unwrap_or(200);

        *self.status.lock().unwrap() = Some(status_code);
        *self.headers.lock().unwrap() = Some(headers);

        Ok(Py::new(py, WSGIWrite)?.into_any())
    }
}
