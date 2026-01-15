use pyo3::{
    IntoPyObjectExt,
    prelude::*,
    types::{PyBytes, PyString},
};
use tokio_tungstenite::tungstenite::Message;

use super::errors::error_proto;
use super::types::{
    WebsocketInboundBytesMessage, WebsocketInboundCloseMessage, WebsocketInboundTextMessage,
};

#[inline]
pub(crate) fn ws_message_into_py(py: Python, message: Message) -> PyResult<Bound<PyAny>> {
    match message {
        Message::Binary(message) => {
            WebsocketInboundBytesMessage::new(PyBytes::new(py, &message).unbind())
                .into_bound_py_any(py)
        }
        Message::Text(message) => {
            WebsocketInboundTextMessage::new(PyString::new(py, &message).unbind())
                .into_bound_py_any(py)
        }
        Message::Close(frame) => {
            let (code, reason) = frame
                .map(|f| {
                    (
                        Some(f.code.into()),
                        (!f.reason.is_empty()).then(|| PyString::new(py, &f.reason).unbind()),
                    )
                })
                .unwrap_or((None, None));
            WebsocketInboundCloseMessage::new(code, reason).into_bound_py_any(py)
        }
        v => {
            log::warn!("Unsupported websocket message received {v:?}");
            error_proto!()
        }
    }
}
