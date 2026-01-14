//! Velo Worker Entry Point
//!
//! RFC-0019: Native Sovereignty (Phase 7.2)
//!
//! This module implements the worker entry point that runs AFTER fork().
//!
//! # Safety
//!
//! The PyO3 initialization (`pyo3::prepare_freethreaded_python()`) MUST occur
//! after fork() to avoid GIL state corruption. This is the critical constraint
//! that differentiates this from the deprecated UDS-based approach.
//!
//! # Architecture
//!
//! ```text
//! Parent (Velo Master)
//!     │
//!     ├── Create listening socket (FD)
//!     ├── Pre-warm Zygote (Python imports)
//!     │
//!     └── fork() ──────────────────────────┐
//!                                          │
//! Child (Granian Worker)                   ▼
//!     │
//!     ├── [worker_entry::run_worker]
//!     │   ├── Initialize PyO3
//!     │   ├── Create SocketHolder from inherited FD
//!     │   ├── Load ASGI app via Python
//!     │   ├── Create CallbackScheduler
//!     │   ├── Create RSGIWorker
//!     │   └── serve_async() ──────────────▶ Handle requests
//!     │
//!     └── exit(0)
//! ```

use super::config::WorkerConfig;
use super::{GranianError, Result};
#[cfg(feature = "granian_native")]
use log::debug;
use log::info;
#[cfg(unix)]
use std::os::unix::io::RawFd;

/// Run the Granian worker after fork().
///
/// # Safety
///
/// This function MUST be called AFTER fork() in the child process.
/// Calling it in the parent will cause GIL state corruption in forked children.
///
/// # Arguments
///
/// * `config` - Worker configuration including socket FD and app path
///
/// # Returns
///
/// This function only returns on error. On success, it blocks forever serving requests.
pub fn run_worker(config: WorkerConfig) -> Result<()> {
    info!(
        "Granian worker {} starting with app: {}",
        config.worker_id, config.app_path
    );

    // Validate configuration
    if config.socket_fd < 0 {
        return Err(GranianError::Socket(
            "Invalid socket FD (must be >= 0)".into(),
        ));
    }

    if config.app_path.is_empty() {
        return Err(GranianError::AppLoad("App path cannot be empty".into()));
    }

    // Run the blocking worker loop
    // This uses a dedicated function to isolate PyO3/Python scope
    run_worker_blocking(config)
}

/// Internal blocking worker implementation.
///
/// This function initializes Python and runs the Granian worker loop.
#[cfg(feature = "granian_native")]
fn run_worker_blocking(config: WorkerConfig) -> Result<()> {
    use pyo3::prelude::*;

    // Step 1: Initialize Python interpreter (MUST be after fork)
    debug!("Initializing Python interpreter post-fork");

    // In embedding mode, we must manually initialize the interpreter
    // before attempting any GIL operations.
    #[allow(deprecated)]
    pyo3::prepare_freethreaded_python();

    // In PyO3 0.27+, we can use Python::with_gil directly or ensure it's initialized
    #[allow(deprecated)]
    Python::with_gil(|py| run_worker_with_python(py, config))
}

/// Stub implementation when granian_native feature is disabled.
#[cfg(not(feature = "granian_native"))]
fn run_worker_blocking(_config: WorkerConfig) -> Result<()> {
    Err(GranianError::WorkerStartup(
        "Granian native workers not enabled. Compile with --features granian_native".into(),
    ))
}

/// Run worker with Python GIL acquired.
#[cfg(feature = "granian_native")]
fn run_worker_with_python(py: pyo3::Python<'_>, config: WorkerConfig) -> Result<()> {
    use granian_core::net::SocketHolder;
    use granian_core::rsgi::serve::RSGIWorker;
    use granian_core::workers::WorkerSignal;
    use pyo3::prelude::*;

    // Step 2: Create SocketHolder from inherited FD
    info!("Creating SocketHolder from FD {}", config.socket_fd);

    #[cfg(any(target_os = "linux", target_os = "freebsd"))]
    let sock = SocketHolder::new(config.socket_fd, false, config.backpressure as i32);

    #[cfg(not(any(target_os = "linux", target_os = "freebsd")))]
    let sock = SocketHolder::new(config.socket_fd, false);

    let sock_py = pyo3::Py::new(py, sock)
        .map_err(|e| GranianError::PyO3(format!("Failed to create SocketHolder: {e}")))?;

    // Step 3: Load ASGI application
    info!("Loading ASGI application: {}", config.app_path);
    let app = load_asgi_app(py, &config)?;

    // Step 4: Create event loop
    info!("Creating asyncio event loop");
    let asyncio = py
        .import("asyncio")
        .map_err(|e| GranianError::PythonInit(format!("Failed to import asyncio: {e}")))?;
    let event_loop = asyncio
        .call_method0("new_event_loop")
        .map_err(|e| GranianError::PythonInit(format!("Failed to create event loop: {e}")))?;
    asyncio
        .call_method1("set_event_loop", (&event_loop,))
        .map_err(|e| GranianError::PythonInit(format!("Failed to set event loop: {e}")))?;

    // Step 5: Initialize CallbackScheduler hooks
    // Step 5: Initialize CallbackScheduler hooks
    debug!("Initializing CallbackScheduler hooks");

    // Step 5: Define required Python hooks (Velo Integration)
    // Granian's CallbackScheduler expects several Python hooks to be set.
    // In a normal Granian launch, these are set by the Python Worker class.
    // Since Velo embeds the worker directly, we must provide these hooks ourselves.
    let globals = pyo3::types::PyDict::new(py);
    py.run(
        pyo3::ffi::c_str!(
            r#"
import asyncio
import inspect

def make_hooks(loop, app):
    # Industrial-Grade Bridge: Detect ASGI vs RSGI signature (RFC-0019)
    try:
        # Standard ASGI is (scope, receive, send) -> 3 args
        # Native RSGI is (scope, proto) -> 2 args
        is_asgi = len(inspect.signature(app).parameters) >= 3
    except:
        # Fallback to RSGI if signature inspection fails
        is_asgi = False

    def _sched(watcher):
        if not is_asgi:
            # Native RSGI Path
            def _start():
                task = loop.create_task(app(watcher.scope, watcher.proto))
                watcher.taskref(task)
            loop.call_soon_threadsafe(_start)
        else:
            # ASGI Compatibility Bridge
            async def asgi_bridge(rsgi_scope, proto):
                # INDICTMENT-05/07 Fix: Build complete ASGI-compliant scope
                # ASGI HTTP scope requires: type, asgi, http_version, method, scheme,
                # path, raw_path, query_string, root_path, headers, server, client, state
                
                scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}}
                
                # Copy all available attributes from RSGIHTTPScope
                for key in dir(rsgi_scope):
                    if not key.startswith('_'):
                        try:
                            val = getattr(rsgi_scope, key)
                            # Skip methods/callables
                            if not callable(val):
                                scope[key] = val
                        except:
                            pass
                
                # Ensure all critical ASGI HTTP scope keys exist with proper defaults
                scope.setdefault('type', 'http')
                scope.setdefault('http_version', '1.1')
                scope.setdefault('method', 'GET')
                scope.setdefault('scheme', 'http')
                scope.setdefault('path', '/')
                scope.setdefault('raw_path', scope.get('path', '/').encode('utf-8'))
                scope.setdefault('query_string', b'')
                scope.setdefault('root_path', '')
                scope.setdefault('headers', [])
                scope.setdefault('server', ('127.0.0.1', 8000))
                scope.setdefault('client', ('127.0.0.1', 0))
                scope.setdefault('state', {})
                scope.setdefault('app', None)
                scope.setdefault('extensions', {})
                
                # Ensure headers is a list of 2-tuples (bytes, bytes) for ASGI
                raw_headers = scope.get('headers', [])
                normalized_headers = []
                
                # RSGIHeaders is a special object - use .items() to iterate
                if hasattr(raw_headers, 'items'):
                    # RSGIHeaders object from Granian - has .items() method
                    try:
                        for k, v in raw_headers.items():
                            if isinstance(k, str):
                                k = k.encode('latin-1')
                            if isinstance(v, str):
                                v = v.encode('latin-1')
                            normalized_headers.append((k, v))
                    except:
                        pass
                elif isinstance(raw_headers, (list, tuple)):
                    for h in raw_headers:
                        try:
                            if isinstance(h, (list, tuple)):
                                if len(h) >= 2:
                                    k, v = h[0], h[1]  # Take only first two
                                    if isinstance(k, str):
                                        k = k.encode('latin-1')
                                    if isinstance(v, str):
                                        v = v.encode('latin-1')
                                    normalized_headers.append((k, v))
                        except:
                            pass  # Skip malformed headers
                scope['headers'] = normalized_headers
                
                # Ensure query_string is bytes
                if isinstance(scope.get('query_string'), str):
                    scope['query_string'] = scope['query_string'].encode('utf-8')
                
                # Ensure client is a proper tuple (host, port) for FastAPI Request.client
                client = scope.get('client')
                if client is None:
                    scope['client'] = ('127.0.0.1', 0)
                elif isinstance(client, (list, tuple)) and len(client) >= 2:
                    scope['client'] = (str(client[0]), int(client[1]) if client[1] else 0)
                else:
                    scope['client'] = ('127.0.0.1', 0)
                
                # Ensure server is a proper tuple (host, port) for Starlette URL construction
                server = scope.get('server')
                if server is None:
                    scope['server'] = ('127.0.0.1', 8000)
                elif isinstance(server, (list, tuple)) and len(server) >= 2:
                    # Starlette URL expects exactly 2-tuple: (host, port)
                    scope['server'] = (str(server[0]), int(server[1]) if server[1] else 0)
                else:
                    scope['server'] = ('127.0.0.1', 8000)
                
                ctx = {"status": 200, "headers": [], "body_received": False, "response_sent": False, "body_chunks": [], "is_streaming": False}
                
                async def receive():
                    # INDICTMENT-06 Fix: Ensure ASGI-compliant receive() messages
                    # FastAPI/Starlette expect: {'type': 'http.request', 'body': b'...', 'more_body': False}
                    if ctx.get("body_received"):
                        # After body is fully received, return disconnect on subsequent calls
                        return {"type": "http.disconnect"}
                    
                    try:
                        msg = await proto.receive()
                        if msg is None:
                            ctx["body_received"] = True
                            return {"type": "http.request", "body": b"", "more_body": False}
                        
                        # If msg is already ASGI-compliant, return as-is
                        if isinstance(msg, dict) and 'type' in msg:
                            if msg.get('type') == 'http.request':
                                ctx["body_received"] = not msg.get('more_body', False)
                            return msg
                        
                        # Otherwise, wrap in ASGI format
                        body = msg if isinstance(msg, bytes) else b""
                        ctx["body_received"] = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    except Exception:
                        ctx["body_received"] = True
                        return {"type": "http.request", "body": b"", "more_body": False}
                
                async def send(msg):
                    m_type = msg.get('type')
                    if m_type == 'http.response.start':
                        ctx["status"] = msg.get('status', 200)
                        ctx["headers"] = msg.get('headers', [])
                        # Detect SSE/EventStream - these need immediate response, not buffering
                        for h in ctx["headers"]:
                            if isinstance(h, (list, tuple)) and len(h) >= 2:
                                hname = h[0].lower() if isinstance(h[0], str) else h[0].decode('latin-1').lower()
                                hval = h[1] if isinstance(h[1], str) else h[1].decode('latin-1')
                                if hname == 'content-type' and 'text/event-stream' in hval:
                                    ctx["is_streaming"] = True
                                    break
                    elif m_type == 'http.response.body':
                        # Guard: Only process HTTP response if proto supports it
                        # WebSocket protocol doesn't have response_bytes
                        if not hasattr(proto, 'response_bytes'):
                            return  # Ignore HTTP responses on WebSocket protocol
                        
                        body = msg.get('body', b'')
                        more_body = msg.get('more_body', False)
                        
                        # SSE/EventStream: send immediately on first body (workaround for sync proto)
                        if ctx["is_streaming"] and not ctx.get("response_sent"):
                            # For SSE, send initial response with first body chunk
                            converted_headers = []
                            for h in ctx["headers"]:
                                if isinstance(h, (list, tuple)) and len(h) == 2:
                                    k, v = h
                                    if isinstance(k, bytes):
                                        k = k.decode('latin-1')
                                    if isinstance(v, bytes):
                                        v = v.decode('latin-1')
                                    converted_headers.append((k, v))
                            proto.response_bytes(ctx["status"], converted_headers, body)
                            ctx["response_sent"] = True
                            return
                        
                        # Regular StreamingResponse: buffer chunks until more_body=False
                        if more_body:
                            ctx["body_chunks"].append(body)
                        else:
                            # Final chunk - combine all buffered chunks and send
                            all_chunks = ctx["body_chunks"] + [body]
                            full_body = b''.join(all_chunks)
                            ctx["body_chunks"] = []
                            
                            # Convert ASGI bytes headers to str headers for proto
                            converted_headers = []
                            for h in ctx["headers"]:
                                if isinstance(h, (list, tuple)) and len(h) == 2:
                                    k, v = h
                                    if isinstance(k, bytes):
                                        k = k.decode('latin-1')
                                    if isinstance(v, bytes):
                                        v = v.decode('latin-1')
                                    converted_headers.append((k, v))
                            proto.response_bytes(ctx["status"], converted_headers, full_body)
                            ctx["response_sent"] = True
                    elif m_type == 'websocket.accept':
                        await proto.accept()
                    elif m_type == 'websocket.send':
                        if 'text' in msg:
                            await proto.send_str(msg['text'])
                        else:
                            await proto.send_bytes(msg['bytes'])
                    elif m_type == 'websocket.close':
                        await proto.close()

                try:
                    await app(scope, receive, send)
                except Exception as e:
                    print(f"ASGI Bridge Runtime Error: {e}")
                    import traceback
                    traceback.print_exc()
                    # Send error response if ASGI app failed before sending response
                    # Only for HTTP - WebSocket protocol doesn't have response_bytes
                    if not ctx.get("response_sent") and scope.get('type') == 'http':
                        try:
                            error_body = f'{{"error": "Internal Server Error", "detail": "{str(e)}"}}'.encode('utf-8')
                            proto.response_bytes(500, [('content-type', 'application/json')], error_body)
                            ctx["response_sent"] = True
                        except:
                            pass  # Ignore if we can't send error response

            def _start():
                task = loop.create_task(asgi_bridge(watcher.scope, watcher.proto))
                watcher.taskref(task)
            loop.call_soon_threadsafe(_start)
        
    def _nop(*args, **kwargs):
        pass
        
    return _sched, _nop

def make_config(kwargs):
    from types import SimpleNamespace
    return SimpleNamespace(**kwargs)
"#
        ),
        Some(&globals),
        None,
    )
    .map_err(|e| GranianError::PythonInit(format!("Failed to define scheduler hooks: {e}")))?;

    let hooks_factory = globals
        .get_item("make_hooks")?
        .ok_or_else(|| GranianError::PythonInit("Failed to find make_hooks in globals".into()))?;

    let hooks_res = hooks_factory.call1((&event_loop, &app))?;
    let (sched_fn, nop_fn): (Bound<'_, PyAny>, Bound<'_, PyAny>) =
        hooks_res.extract().map_err(|e| {
            GranianError::PythonInit(format!("Failed to initialize scheduler hooks: {e}"))
        })?;

    // Step 5.1: Create CallbackScheduler
    debug!("Creating CallbackScheduler");
    let scheduler = create_callback_scheduler(py, &event_loop, &app, Some(&nop_fn), Some(&nop_fn))?;

    // Set the internal _schedule_fn used by CallbackScheduler.schedule()
    scheduler
        .bind(py)
        .setattr("_schedule_fn", sched_fn)
        .map_err(|e| GranianError::PythonInit(format!("Failed to set _schedule_fn: {e}")))?;

    // Step 6: Create RSGIWorker
    debug!("Creating RSGIWorker");
    let (
        ssl_enabled,
        ssl_cert,
        ssl_key,
        ssl_key_password,
        ssl_protocol_min,
        ssl_ca,
        ssl_crl,
        ssl_client_verify,
    ) = match &config.tls_config {
        Some(tls) => (
            true,
            Some(tls.cert_path.clone()),
            Some(tls.key_path.clone()),
            tls.key_password.clone(),
            tls.protocol_min.as_str(),
            tls.ca_path.clone(),
            tls.crl_paths.clone(),
            tls.client_verify,
        ),
        None => (false, None, None, None, "1.3", None, Vec::new(), false),
    };

    let make_config = globals
        .get_item("make_config")?
        .ok_or_else(|| GranianError::PythonInit("Failed to find make_config in globals".into()))?;

    let http1_dict = pyo3::types::PyDict::new(py);
    http1_dict.set_item(
        "header_read_timeout",
        config.http1_config.header_read_timeout.as_millis(),
    )?;
    http1_dict.set_item("keep_alive", config.http1_config.keep_alive)?;
    http1_dict.set_item("max_buffer_size", config.http1_config.max_buffer_size)?;
    http1_dict.set_item("pipeline_flush", config.http1_config.pipeline_flush)?;
    let http1_opts = make_config.call1((http1_dict,))?;

    let http2_dict = pyo3::types::PyDict::new(py);
    http2_dict.set_item("adaptive_window", config.http2_config.adaptive_window)?;
    http2_dict.set_item(
        "initial_connection_window_size",
        config.http2_config.initial_connection_window_size,
    )?;
    http2_dict.set_item(
        "initial_stream_window_size",
        config.http2_config.initial_stream_window_size,
    )?;
    http2_dict.set_item(
        "keep_alive_interval",
        config
            .http2_config
            .keep_alive_interval
            .map(|d| d.as_millis()),
    )?;
    http2_dict.set_item(
        "keep_alive_timeout",
        config.http2_config.keep_alive_timeout.as_secs(),
    )?;
    http2_dict.set_item(
        "max_concurrent_streams",
        config.http2_config.max_concurrent_streams,
    )?;
    http2_dict.set_item("max_frame_size", config.http2_config.max_frame_size)?;
    http2_dict.set_item("max_headers_size", config.http2_config.max_headers_size)?;
    http2_dict.set_item(
        "max_send_buffer_size",
        config.http2_config.max_send_buffer_size,
    )?;
    let http2_opts = make_config.call1((http2_dict,))?;

    let worker = RSGIWorker::new(
        py,
        config.worker_id,
        sock_py,
        config.threads,
        config.blocking_threads,
        config.py_threads,
        config.py_threads_idle_timeout,
        config.backpressure,
        &config.http_mode,
        Some(http1_opts.unbind()),
        Some(http2_opts.unbind()),
        config.websockets_enabled,
        None, // static_files
        ssl_enabled,
        ssl_cert,
        ssl_key,
        ssl_key_password,
        ssl_protocol_min,
        ssl_ca,
        ssl_crl,
        ssl_client_verify,
    )
    .map_err(|e| GranianError::WorkerStartup(format!("Failed to create RSGIWorker: {e}")))?;

    // Step 7: Create WorkerSignal for shutdown
    debug!("Creating WorkerSignal");
    let signal = pyo3::Py::new(py, WorkerSignal::new())
        .map_err(|e| GranianError::PyO3(format!("Failed to create WorkerSignal: {e}")))?;

    // Step 8: Start serving
    info!(
        "Granian worker {} ready, serving on FD {}",
        config.worker_id, config.socket_fd
    );

    // serve_async returns a Python awaitable
    debug!("Calling serve_async");
    let serve_future = worker.serve_async(scheduler, &event_loop, signal);

    // Run the event loop until completion
    debug!("Starting event loop run_until_complete");
    event_loop
        .call_method1("run_until_complete", (serve_future,))
        .map_err(|e| GranianError::WorkerStartup(format!("Event loop error: {e}")))?;

    info!("Granian worker {} shutting down", config.worker_id);
    Ok(())
}

/// Load an ASGI application from a module path.
///
/// # Arguments
///
/// * `py` - Python GIL guard
/// * `app_path` - Path in format "module:app" (e.g., "main:app")
#[cfg(feature = "granian_native")]
fn load_asgi_app<'py>(
    py: pyo3::Python<'py>,
    config: &WorkerConfig,
) -> Result<pyo3::Bound<'py, pyo3::PyAny>> {
    use pyo3::prelude::*;
    use pyo3::types::PyList;

    let app_path = &config.app_path;

    // Add project directory to sys.path (RFC-0012)
    if let Some(ref project_dir) = config.project_dir {
        let sys = py.import("sys")?;
        let path: Bound<'py, PyList> = sys.getattr("path")?.cast_into()?;
        path.insert(0, project_dir.to_string_lossy())?;
        debug!("Added project dir to sys.path: {:?}", project_dir);
    }

    // Also add "." to be safe
    let sys = py.import("sys")?;
    let path: Bound<'py, PyList> = sys.getattr("path")?.cast_into()?;
    path.insert(0, ".")?;

    // Add PYTHONPATH entries to sys.path (for test harness compatibility)
    if let Ok(pythonpath) = std::env::var("PYTHONPATH") {
        for entry in pythonpath.split(':') {
            if !entry.is_empty() {
                path.insert(0, entry)?;
                debug!("Added PYTHONPATH entry to sys.path: {}", entry);
            }
        }
    }

    let parts: Vec<&str> = app_path.split(':').collect();
    if parts.len() != 2 {
        return Err(GranianError::AppLoad(format!(
            "Invalid app path format: '{app_path}'. Expected 'module:app'"
        )));
    }

    let module_name = parts[0];
    let app_name = parts[1];

    debug!("Loading module '{}' attribute '{}'", module_name, app_name);

    // Import the module
    let module = py.import(module_name).map_err(|e| {
        GranianError::AppLoad(format!("Failed to import module '{module_name}': {e}"))
    })?;

    // Get the app attribute
    let app = module.getattr(app_name).map_err(|e| {
        GranianError::AppLoad(format!(
            "Failed to get attribute '{app_name}' from module '{module_name}': {e}"
        ))
    })?;

    // Verify it's callable
    if !app.is_callable() {
        return Err(GranianError::AppLoad(format!(
            "'{app_path}' is not callable. ASGI apps must be callable."
        )));
    }

    Ok(app)
}

/// Create a CallbackScheduler for the RSGI protocol.
#[cfg(feature = "granian_native")]
fn create_callback_scheduler<'py>(
    py: pyo3::Python<'py>,
    event_loop: &pyo3::Bound<'py, pyo3::PyAny>,
    app: &pyo3::Bound<'py, pyo3::PyAny>,
    tenter: Option<&pyo3::Bound<'py, pyo3::PyAny>>,
    texit: Option<&pyo3::Bound<'py, pyo3::PyAny>>,
) -> Result<pyo3::Py<granian_core::callbacks::CallbackScheduler>> {
    use granian_core::callbacks::CallbackScheduler;
    use pyo3::prelude::*;

    // Get asyncio task utilities
    let asyncio = py
        .import("asyncio")
        .map_err(|e| GranianError::PythonInit(format!("Failed to import asyncio: {e}")))?;

    let task_cls = asyncio
        .getattr("Task")
        .map_err(|e| GranianError::PythonInit(format!("Failed to get Task class: {e}")))?;

    // For CallbackScheduler, we need:
    // - event_loop: the asyncio event loop
    // - cb: the callback function (the ASGI app)
    // - aio_task: Task class
    // - aio_tenter: Task.__enter__ equivalent (context manager)
    // - aio_texit: Task.__exit__ equivalent

    // Get task context methods
    let task_enter = tenter.cloned().unwrap_or_else(|| py.None().into_bound(py));
    let task_exit = texit.cloned().unwrap_or_else(|| py.None().into_bound(py));

    // Create the scheduler
    let scheduler = CallbackScheduler::new(
        py,
        event_loop.clone().unbind(),
        app.clone().unbind(),
        task_cls.unbind(),
        task_enter.unbind(),
        task_exit.unbind(),
    );

    pyo3::Py::new(py, scheduler)
        .map_err(|e| GranianError::PyO3(format!("Failed to create CallbackScheduler: {e}")))
}

/// Reset signal handlers in child process after fork.
///
/// This is necessary to prevent the child from inheriting signal handlers
/// that may be tied to parent-specific state (like shutdown coordination).
#[cfg(unix)]
pub fn reset_signal_handlers() {
    use libc::{SIG_DFL, SIGINT, SIGTERM, SIGUSR1, SIGUSR2, signal};

    unsafe {
        signal(SIGTERM, SIG_DFL);
        signal(SIGINT, SIG_DFL);
        signal(SIGUSR1, SIG_DFL);
        signal(SIGUSR2, SIG_DFL);
    }
}

/// Close all file descriptors except the specified ones.
///
/// This is a security measure to prevent FD leakage from parent to child.
#[cfg(unix)]
pub fn close_range_except(keep_fds: &[RawFd]) {
    use std::collections::HashSet;
    use std::fs;

    let keep: HashSet<RawFd> = keep_fds.iter().copied().collect();
    let always_keep = [0, 1, 2]; // stdin, stdout, stderr

    // TITANIUM RULE: Efficient FD Hygiene
    // Instead of brute-forcing 3..65535, we iterate over /dev/fd (macOS) or /proc/self/fd (Linux)
    // to find exactly which FDs are open. This is faster and cleaner.

    #[cfg(target_os = "macos")]
    let fd_dir = "/dev/fd";
    #[cfg(target_os = "linux")]
    let fd_dir = "/proc/self/fd";
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    let fd_dir = "";

    if fd_dir.is_empty() {
        // Fallback to brute force for safety if dir is empty/not defined
        for fd in 3..1024 {
            if !keep.contains(&fd) && !always_keep.contains(&fd) {
                unsafe {
                    libc::close(fd);
                }
            }
        }
        return;
    }

    if let Ok(entries) = fs::read_dir(fd_dir) {
        let mut to_close = Vec::new();
        for entry in entries.flatten() {
            let Ok(fd_str) = entry.file_name().into_string() else {
                continue;
            };
            let Ok(fd) = fd_str.parse::<RawFd>() else {
                continue;
            };
            if fd > 2 && !keep.contains(&fd) && !always_keep.contains(&fd) {
                to_close.push(fd);
            }
        }

        // Now close them all safely
        for fd in to_close {
            unsafe {
                libc::close(fd);
            }
        }
    }

    // Fallback to brute force for safety if dir iteration fails
    for fd in 3..1024 {
        if !keep.contains(&fd) && !always_keep.contains(&fd) {
            unsafe {
                libc::close(fd);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_worker_config_validation() {
        let config = WorkerConfig::new(0, -1, "main:app");
        let result = run_worker(config);
        assert!(result.is_err());

        if let Err(GranianError::Socket(msg)) = result {
            assert!(msg.contains("Invalid socket FD"));
        } else {
            panic!("Expected Socket error");
        }
    }

    #[test]
    fn test_empty_app_path() {
        let config = WorkerConfig::new(0, 3, "");
        let result = run_worker(config);
        assert!(result.is_err());

        if let Err(GranianError::AppLoad(msg)) = result {
            assert!(msg.contains("empty"));
        } else {
            panic!("Expected AppLoad error");
        }
    }
}
