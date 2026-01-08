use std::io::Write;
use std::os::unix::io::AsRawFd;
use tempfile::NamedTempFile;
// use velo::shm::alignment; (Removed unused import)
use velo::shm::registry::MemoryRegistry;

#[test]
fn test_registry_create_segment() {
    let registry = MemoryRegistry::new();

    // Create valid dummy safetensors file (8 bytes len + header)
    // If we passed random text, H-29 parser would interpret first 8 bytes as huge length
    // and fail with "Header too large" or "File too small".
    let mut buffer = Vec::new();
    // Length 1
    buffer.extend_from_slice(&1u64.to_le_bytes());
    // Header
    buffer.push(b'{');
    // Data (optional but we want to be valid)
    buffer.extend_from_slice(b"DATA");

    let mut tmp = NamedTempFile::new().unwrap();
    tmp.write_all(&buffer).unwrap();

    // Create segment
    let file = registry
        .create_segment("test_seg", tmp.path())
        .expect("Failed to create segment");

    // Verify file is valid
    assert!(file.as_raw_fd() > 0);
}

#[test]
fn test_alignment_logic() {
    // L4-SHM-11 (Alignment)
    assert_eq!(velo::shm::alignment::calculate_padding(56).unwrap(), 0);
    assert_eq!(velo::shm::alignment::calculate_padding(1).unwrap(), 55);
}

#[test]
fn test_registry_enforces_padding() {
    // H-29 Red Phase: Write a test that expects the Registry to align data.
    let registry = MemoryRegistry::new();

    let mut buffer = Vec::new();
    // 8 bytes length (u64 little endian, say length=1)
    buffer.extend_from_slice(&1u64.to_le_bytes());
    // 1 byte header
    buffer.push(b'{');
    // Data
    buffer.extend_from_slice(b"DATA");

    let mut tmp = NamedTempFile::new().unwrap();
    tmp.write_all(&buffer).unwrap();

    // This assumes create_segment parses and pads.
    let file = registry.create_segment("padded_seg", tmp.path()).unwrap();
    let fd = file.as_raw_fd();

    // Verify content logic using mmap (safe across macOS/Linux)
    // We expect: [8 bytes len] [1 byte header] [55 bytes zero padding] [4 bytes DATA]
    let total_size = 68;

    let ptr = unsafe {
        libc::mmap(
            std::ptr::null_mut(),
            total_size,
            libc::PROT_READ,
            libc::MAP_SHARED,
            fd,
            0,
        )
    };

    assert_ne!(ptr, libc::MAP_FAILED, "Failed to mmap for verification");

    let slice = unsafe { std::slice::from_raw_parts(ptr as *const u8, total_size) };

    // Check first 8 bytes (len)
    assert_eq!(&slice[0..8], &1u64.to_le_bytes());

    // Check header
    assert_eq!(slice[8], b'{');

    // Check padding (55 null bytes)
    // 8 + 1 = 9.
    // Padding starts at 9, ends at 64. (Length 55).
    let padding = &slice[9..64];
    assert!(
        padding.iter().all(|&b| b == 0),
        "Padding bytes must be zero!"
    );

    // Check data starts at 64
    assert_eq!(&slice[64..68], b"DATA");

    unsafe {
        libc::munmap(ptr, total_size);
    }
}
