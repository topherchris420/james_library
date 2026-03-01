use criterion::{black_box, criterion_group, criterion_main, Criterion};

fn benchmark_truncate_with_ellipsis(c: &mut Criterion) {
    let long_text = "x".repeat(8_192);
    let short_text = "hello world".to_string();

    c.bench_function("truncate_with_ellipsis/long_8k_to_256", |b| {
        b.iter(|| {
            let out = zeroclaw::util::truncate_with_ellipsis(black_box(&long_text), 256);
            black_box(out);
        })
    });

    c.bench_function("truncate_with_ellipsis/short_unchanged", |b| {
        b.iter(|| {
            let out = zeroclaw::util::truncate_with_ellipsis(black_box(&short_text), 256);
            black_box(out);
        })
    });
}

criterion_group!(benches, benchmark_truncate_with_ellipsis);
criterion_main!(benches);
