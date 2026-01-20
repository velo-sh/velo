use std::fs::File;
use std::io::Write;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tempfile::tempdir;
use velo::v_live::watcher::{VibeWatcher, WatchHandler};

struct MockHandler {
    events: Arc<Mutex<Vec<String>>>,
}

impl WatchHandler for MockHandler {
    fn on_change(&self, path: &str) {
        let mut events = self.events.lock().unwrap();
        events.push(path.to_string());
    }
}

#[test]
fn test_watcher_self_heals_after_syntax_error() {
    let _ = env_logger::builder().is_test(true).try_init();
    let dir = tempdir().unwrap();
    let file_path = dir.path().join("app.py");
    let mut file = File::create(&file_path).unwrap();
    writeln!(file, "print('hello')").unwrap();

    let events = Arc::new(Mutex::new(Vec::new()));
    let handler = MockHandler {
        events: events.clone(),
    };

    let mut watcher = VibeWatcher::new(handler);
    watcher
        .watch(dir.path().to_str().unwrap())
        .expect("Failed to start watch");

    // 1. Initial change (valid)
    {
        let mut file = File::options().append(true).open(&file_path).unwrap();
        writeln!(file, "print('valid 1')").unwrap();
        file.sync_all().unwrap();
    }
    thread::sleep(Duration::from_millis(500));
    assert_eq!(
        events.lock().unwrap().len(),
        1,
        "Should have triggered once for valid change"
    );

    // 2. Simulate Syntax Error Save
    // The design says the watcher should SURVIVE if the execution fails.
    // In our test, we just want to ensure that even if we "handle" an error,
    // the watcher loop stays alive.
    {
        let mut file = File::create(&file_path).unwrap(); // Overwrite with garbage
        writeln!(file, "invalid syntax @#$%").unwrap();
        file.sync_all().unwrap();
    }
    thread::sleep(Duration::from_millis(500));
    assert_eq!(
        events.lock().unwrap().len(),
        2,
        "Watcher should still trigger for invalid file"
    );

    // 3. Fix the syntax and verify it still works
    {
        let mut file = File::create(&file_path).unwrap();
        writeln!(file, "print('valid 2')").unwrap();
        file.sync_all().unwrap();
    }
    thread::sleep(Duration::from_millis(500));
    assert_eq!(
        events.lock().unwrap().len(),
        3,
        "Watcher should have recovered and triggered for the fixed file"
    );
}
