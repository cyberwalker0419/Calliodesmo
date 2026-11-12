"""P8 Task 4：温度缩放校准器单测（公式 / 网格搜索 / 读写幂等）。"""

from __future__ import annotations

import pytest

from calliodesmo.verification.calibration import (
    CalibrationParams,
    CalibrationSlice,
    Calibrator,
    fit_temperature,
    load_calibration,
    logit,
    save_calibration,
    sigmoid,
    temperature_scale,
)


class TestTemperatureScale:
    def test_identity_at_one(self):
        assert temperature_scale(0.9, 1.0) == pytest.approx(0.9)

    def test_softens_overconfidence(self):
        assert temperature_scale(0.9, 2.0) < 0.9
        assert temperature_scale(0.9, 2.0) > 0.5

    def test_sharpens_underconfidence(self):
        assert temperature_scale(0.6, 0.5) > 0.6

    def test_extremes_clamped(self):
        assert 0.0 < temperature_scale(0.0, 2.0) < 0.01
        assert 0.99 < temperature_scale(1.0, 2.0) < 1.0

    def test_invalid_temperature(self):
        with pytest.raises(ValueError):
            temperature_scale(0.5, 0.0)

    def test_logit_sigmoid_roundtrip(self):
        for p in (0.01, 0.2, 0.5, 0.8, 0.99):
            assert sigmoid(logit(p)) == pytest.approx(p, abs=1e-6)


class TestFitTemperature:
    def test_overconfident_data_selects_softening(self):
        # 100 条 conf=0.95 但仅 50% 正确 -> 应选 T > 1
        confidences = [0.95] * 100
        outcomes = [True] * 50 + [False] * 50
        temperature = fit_temperature(confidences, outcomes)
        assert temperature > 1.0

    def test_well_calibrated_data_stays_near_identity(self):
        # conf=0.7 且 70% 正确 -> 最优温度应接近 1
        confidences = [0.7] * 100
        outcomes = [True] * 70 + [False] * 30
        assert 0.8 <= fit_temperature(confidences, outcomes) <= 1.2

    def test_empty_returns_identity(self):
        assert fit_temperature([], []) == 1.0

    def test_all_same_class_returns_identity(self):
        assert fit_temperature([0.9] * 100, [True] * 100) == 1.0

    def test_insufficient_samples_returns_identity(self):
        assert fit_temperature([0.9] * 10, [True] * 5 + [False] * 5) == 1.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            fit_temperature([0.5], [True, False])

    def test_scaling_reduces_ece(self):
        from calliodesmo.eval.metrics_grounding import expected_calibration_error

        confidences = [0.95] * 100
        outcomes = [True] * 50 + [False] * 50
        before, _, _ = expected_calibration_error(confidences, outcomes)
        temperature = fit_temperature(confidences, outcomes)
        after, _, _ = expected_calibration_error(
            [temperature_scale(c, temperature) for c in confidences], outcomes
        )
        assert after < before


class TestCalibrator:
    def test_slice_lookup(self):
        calibrator = Calibrator(
            params=CalibrationParams(
                default_temperature=1.0,
                slices=(
                    CalibrationSlice(
                        model="m1", prompt_version="qa.v1", temperature=1.5, sample_count=120
                    ),
                ),
            )
        )
        assert calibrator.temperature_for(model="m1", prompt_version="qa.v1") == 1.5
        assert calibrator.calibrate(0.9, model="m1", prompt_version="qa.v1") < 0.9

    def test_missing_slice_identity_with_warning(self):
        calibrator = Calibrator()
        assert calibrator.calibrate(0.9, model="unknown", prompt_version="x") == pytest.approx(0.9)
        assert calibrator.warnings


class TestPersistence:
    def test_roundtrip_and_idempotent(self, tmp_path):
        path = tmp_path / "calibration.yaml"
        params = CalibrationParams(
            default_temperature=1.0,
            slices=(
                CalibrationSlice("m2", "b.v1", 1.2, 50),
                CalibrationSlice("m1", "a.v1", 1.5, 120),
            ),
        )
        save_calibration(params, path)
        first = path.read_text(encoding="utf-8")
        save_calibration(params, path)
        assert path.read_text(encoding="utf-8") == first
        loaded = load_calibration(path)
        assert loaded.default_temperature == 1.0
        assert [(s.model, s.prompt_version, s.temperature) for s in loaded.slices] == [
            ("m1", "a.v1", 1.5),
            ("m2", "b.v1", 1.2),
        ]

    def test_missing_file_defaults(self, tmp_path):
        params = load_calibration(tmp_path / "nope.yaml")
        assert params == CalibrationParams()

    def test_malformed_file_defaults(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("not: [valid", encoding="utf-8")
        assert load_calibration(path) == CalibrationParams()

    def test_invalid_temperature_falls_back(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_text(
            "default_temperature: -1\nslices:\n  - model: m\n    prompt_version: v\n"
            "    temperature: 0\n    sample_count: 5\n",
            encoding="utf-8",
        )
        params = load_calibration(path)
        assert params.default_temperature == 1.0
        assert params.slices[0].temperature == 1.0
