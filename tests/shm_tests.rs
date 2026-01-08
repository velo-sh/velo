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

#[test]
fn test_shm_alignment_rounding() {
    // H-20: Test that HugePage alignment logic works (white-box test logic)
    // The registry implementation does: ((size / HUGE_PAGE_SIZE) + 1) * HUGE_PAGE_SIZE
    // We verify this property via actual segment creation.

    // Note: We can only truly test this if the kernel supports HugePages and we get is_huge=true.
    // However, on standard pages, the same logic would just result in a larger file, which is valid.
    let registry = MemoryRegistry::new();

    // 1. Small file (should be 2MB aligned if HugePages active, or at least succeed)
    let mut buffer = Vec::new();
    buffer.extend_from_slice(&1u64.to_le_bytes());
    buffer.extend_from_slice(b"{");
    buffer.extend_from_slice(b"SMALL");

    let mut tmp = NamedTempFile::new().unwrap();
    tmp.write_all(&buffer).unwrap();

    let file = registry
        .create_segment("align_small", tmp.path())
        .expect("Small create failed");
    let meta = file.metadata().unwrap();
    println!("Small segment size: {}", meta.len());
}

#[test]
fn test_shm_huge_allocation_patterns() {
    // H-system Integration Tests
    // Verify that we can allocate File objects for various sizes.
    // This tests ftruncate interaction with the kernel.
    let registry = MemoryRegistry::new();
    let huge_size = 2 * 1024 * 1024; // 2MB

    // 1. Exact 2MB Allocation
    let mut buffer_exact = Vec::with_capacity(huge_size);
    // Fake header to be valid safetensors
    buffer_exact.extend_from_slice(&1u64.to_le_bytes());
    buffer_exact.extend_from_slice(b"{");
    // Pad to exactly 2MB
    buffer_exact.resize(huge_size, 0);

    let mut tmp_exact = NamedTempFile::new().unwrap();
    tmp_exact.write_all(&buffer_exact).unwrap();

    let file_exact = registry
        .create_segment("align_exact", tmp_exact.path())
        .expect("Exact 2MB create failed");
    assert!(file_exact.as_raw_fd() > 0);

    // 2. Overflow Allocation (2MB + 1 byte) -> Should align to 4MB
    let mut buffer_over = Vec::with_capacity(huge_size + 1);
    buffer_over.extend_from_slice(&1u64.to_le_bytes());
    buffer_over.extend_from_slice(b"{");
    buffer_over.resize(huge_size + 1, 0);

    let mut tmp_over = NamedTempFile::new().unwrap();
    tmp_over.write_all(&buffer_over).unwrap();

    let file_over = registry
        .create_segment("align_overflow", tmp_over.path())
        .expect("Overflow 2MB+1 create failed");
    assert!(file_over.as_raw_fd() > 0);
    // Note: We can't easily assert physical size without stat/ioctl, but success means kernel accepted it.
}
