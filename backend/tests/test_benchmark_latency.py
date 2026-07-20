from app.templates.number_line.params import NumberLineParams, NumberLineStep


def test_run_benchmark_measures_each_scene_without_calling_bedrock(tmp_path, monkeypatch):
    from scripts import benchmark_latency

    params = NumberLineParams(
        start=4,
        steps=[
            NumberLineStep(operation="add", amount=3),
            NumberLineStep(operation="subtract", amount=1),
        ],
    )
    extracted = []
    rendered = []

    def fake_extract(source_text, params_cls):
        extracted.append((source_text, params_cls))
        return params

    def fake_render(template, received_params, output_path):
        rendered.append((template, received_params, output_path))
        output_path.write_bytes(b"mp4")
        return output_path

    monkeypatch.setattr(benchmark_latency, "extract_params", fake_extract)
    monkeypatch.setattr(benchmark_latency, "render_scene_to_mp4", fake_render)

    results = benchmark_latency.run_benchmark(tmp_path)

    assert len(results) == 3
    assert len(extracted) == 3
    assert len(rendered) == 3
    assert all(result["total_seconds"] >= 0 for result in results)
    assert all(path.exists() for _, _, path in rendered)
