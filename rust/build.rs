fn main() {
    // Compile the C shim only when asked (the `mb` feature), so the default
    // build has no dependency on ISA-L Crypto.
    if std::env::var_os("CARGO_FEATURE_MB").is_some() {
        cc::Build::new()
            .file("src/pow_mb.c")
            .include("/usr/include")
            .flag("-O3")
            .compile("pow_mb");
        println!("cargo:rustc-link-lib=dylib=isal_crypto");
        // Fallback if ISA-L was installed under /usr/local/lib
        println!("cargo:rustc-link-search=native=/usr/local/lib");
    }
    println!("cargo:rerun-if-changed=src/pow_mb.c");
    println!("cargo:rerun-if-changed=build.rs");
}
