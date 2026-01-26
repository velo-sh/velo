#![no_main]
use libfuzzer_sys::fuzz_target;
use velo_protocol::ZygoteCommand;
use rmp_serde::{encode, decode};

// This target uses structured fuzzing: libfuzzer generates a ZygoteCommand directly
fuzz_target!(|cmd: ZygoteCommand| {
    // Roundtrip verification
    let serialized = encode::to_vec(&cmd).expect("Serialization of a valid ZygoteCommand should never fail");
    let deserialized: ZygoteCommand = decode::from_slice(&serialized).expect("Deserialization of a self-serialized ZygoteCommand should never fail");
    assert_eq!(cmd, deserialized, "Roundtrip must be loss-less for ZygoteCommand");
});

// We can't have two fuzz_target! macros in the same file that libfuzzer will treat as entry points easily,
// but for our purposes, testing ZygoteCommand is the priority as it handles complex script/module configurations.
