#![no_main]
use libfuzzer_sys::fuzz_target;
use velo_protocol::{ZygoteCommand, ZygoteResponse};
use rmp_serde::{encode, decode};

fuzz_target!(|data: &[u8]| {
    // 1. Try to deserialize the raw data as a ZygoteCommand
    // This tests the robustness of the deserializer against arbitrary input
    if let Ok(cmd) = decode::from_slice::<ZygoteCommand>(data) {
        // Carry out roundtrip if deserialization succeeds
        let serialized = encode::to_vec(&cmd).expect("Serialization of a valid command should never fail");
        let deserialized: ZygoteCommand = decode::from_slice(&serialized).expect("Deserialization of a self-serialized command should never fail");
        assert_eq!(cmd, deserialized, "Roundtrip must be loss-less");
    }

    // 2. Try to deserialize the raw data as a ZygoteResponse
    if let Ok(resp) = decode::from_slice::<ZygoteResponse>(data) {
        let serialized = encode::to_vec(&resp).expect("Serialization of a valid response should never fail");
        let deserialized: ZygoteResponse = decode::from_slice(&serialized).expect("Deserialization of a self-serialized response should never fail");
        assert_eq!(resp, deserialized, "Roundtrip must be loss-less");
    }

    // 3. Test Arbitrary generation (if Arbitrary is implemented)
    // We can also let libfuzzer generate valid structs directly if we use the right signature
});

// We can also add a specialized target for structured fuzzing
// This requires a different fuzz_target! macro usage if we wanted libfuzzer to generate the struct
