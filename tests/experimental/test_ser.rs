use serde::{Serialize, Deserialize};
#[derive(Debug, Serialize, Deserialize)]
pub enum Test {
    Ready,
    Forked { pid: u32, code: Option<i32> },
}
fn main() {
    let r = Test::Ready;
    println!("Ready: {:02x?}", rmp_serde::to_vec(&r).unwrap());
    let f = Test::Forked { pid: 123, code: Some(0) };
    println!("Forked: {:02x?}", rmp_serde::to_vec(&f).unwrap());
}
