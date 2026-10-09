//! Bakes a digest of this crate's own source into the extension (PR2b, #24).
//!
//! A validated profile names the encoder by this digest, so rebuilding from
//! different source withdraws it until it is measured again. Source, not the
//! binary: the same source builds the same digest here and in the image.

use std::fs;
use std::path::Path;

use sha2::{Digest, Sha256};

fn main() {
    let mut files: Vec<String> = fs::read_dir("src")
        .expect("src exists")
        .filter_map(|e| e.ok())
        .map(|e| e.path().to_string_lossy().into_owned())
        .filter(|p| p.ends_with(".rs"))
        .collect();
    files.sort();
    files.push("Cargo.lock".into());
    files.push("Cargo.toml".into());
    let mut hasher = Sha256::new();
    for name in &files {
        let bytes = fs::read(Path::new(name)).expect("readable source");
        let label = name.replace('\\', "/");
        hasher.update((label.len() as u64).to_be_bytes());
        hasher.update(label.as_bytes());
        hasher.update((bytes.len() as u64).to_be_bytes());
        hasher.update(&bytes);
        println!("cargo:rerun-if-changed={name}");
    }
    let digest = hasher.finalize();
    let hex: String = digest.iter().take(8).map(|b| format!("{b:02x}")).collect();
    println!("cargo:rustc-env=NEXUS_NATIVE_SOURCE_DIGEST={hex}");
}
