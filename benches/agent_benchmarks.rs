use criterion::{black_box, criterion_group, criterion_main, Criterion};

fn benchmark_noop(c: &mut Criterion) {
    c.bench_function("noop", |b| {
        b.iter(|| {
            black_box(42_u64);
        })
    });
}

criterion_group!(benches, benchmark_noop);
criterion_main!(benches);
