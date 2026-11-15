"""P8 Task 4：置信度校准器（温度缩放 + 参数落盘，纯 Python 无 numpy）。

口径（P8 关键决策 5）：
- 一维温度缩放：``sigmoid(logit(p) / T)``；``T=1`` 为恒等，``T>1`` 软化过度自信；
- 参数按 ``model + prompt_version`` 切片，缺切片回退 ``default_temperature``
  并记 warning（不静默假设已校准）；
- 拟合为一维网格搜索（默认 0.5–3.0，步长 0.05），目标函数为 10 桶 ECE
  （与 ``eval/metrics_grounding.expected_calibration_error`` 同一事实源）；
- 样本不足（< ``MIN_CALIBRATION_SAMPLES``）或全同类样本不拟合，保持恒等并留痕；
- 参数文件 ``config/calibration.yaml`` 读写幂等（切片排序 + 温度定精度）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from calliodesmo.eval.metrics_grounding import ReliabilityBin, expected_calibration_error

#: 样本不足阈值：低于该值只报参考值，不落拟合参数
MIN_CALIBRATION_SAMPLES = 100
#: 默认网格（温度 > 1 软化过度自信；< 1 增强欠自信）
DEFAULT_GRID: tuple[float, ...] = tuple(round(0.5 + 0.05 * i, 2) for i in range(51))
_EPS = 1e-6
_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "calibration.yaml"


@dataclass(frozen=True)
class CalibrationSlice:
    """单切片参数：模型 + 提示词版本维度的温度与拟合样本量。"""

    model: str
    prompt_version: str
    temperature: float
    sample_count: int


@dataclass(frozen=True)
class CalibrationParams:
    """校准参数集：默认温度 + 切片列表。"""

    default_temperature: float = 1.0
    slices: tuple[CalibrationSlice, ...] = ()


@dataclass(frozen=True)
class CrossValidatedECE:
    """交叉验证校准报告：汇总 ECE、可靠性表、各折温度与留出样本数。

    ``ece`` 在**全部样本**上计算：每条样本由「不含自己的那一折」拟合的温度校准，
    再统一分箱——样本利用率 100%，统计上比单次奇偶留出更稳（P9 关键决策 4）。
    """

    ece: float
    table: list[ReliabilityBin]
    sample_count: int
    folds: int
    temperatures: tuple[float, ...]
    fold_sizes: tuple[int, ...]


def cross_validated_calibration(
    confidences: list[float],
    outcomes: list[bool],
    *,
    folds: int = 5,
    bins: int = 10,
    grid: tuple[float, ...] = DEFAULT_GRID,
    min_train_samples: int = 30,
) -> CrossValidatedECE:
    """K 折交叉验证校准：按 ``index % folds`` 分折，逐折在训练集拟合温度并校准留出集。

    参数:
        confidences / outcomes: 等长的置信-正确性样本。
        folds: 折数（≥2；样本不足折数时允许空折）。
        bins: ECE 分箱数。
        grid: 温度网格。
        min_train_samples: 单折训练样本下限；不足时该折用恒等温度（防小样本过拟合）。

    返回:
        ``CrossValidatedECE``；空样本返回全零报告（``temperatures`` / ``fold_sizes`` 为空）。
    """
    if len(confidences) != len(outcomes):
        raise ValueError("confidences 与 outcomes 长度必须一致")
    if folds < 2:
        raise ValueError("folds 必须 ≥ 2")
    n = len(confidences)
    if n == 0:
        return CrossValidatedECE(
            ece=0.0, table=[], sample_count=0, folds=folds, temperatures=(), fold_sizes=()
        )

    calibrated: list[float] = [0.0] * n
    temperatures: list[float] = []
    fold_sizes: list[int] = []
    for fold in range(folds):
        holdout = [i for i in range(n) if i % folds == fold]
        train = [i for i in range(n) if i % folds != fold]
        fold_sizes.append(len(holdout))
        temperature = fit_temperature(
            [confidences[i] for i in train],
            [outcomes[i] for i in train],
            grid=grid,
            bins=bins,
            min_samples=min_train_samples,
        )
        temperatures.append(temperature)
        for i in holdout:
            calibrated[i] = temperature_scale(confidences[i], temperature)

    ece, table, sample_count = expected_calibration_error(calibrated, outcomes, bins=bins)
    return CrossValidatedECE(
        ece=ece,
        table=table,
        sample_count=sample_count,
        folds=folds,
        temperatures=tuple(temperatures),
        fold_sizes=tuple(fold_sizes),
    )


@dataclass
class Calibrator:
    """运行时校准器：按切片取温度并变换置信。"""

    params: CalibrationParams = field(default_factory=CalibrationParams)
    warnings: list[str] = field(default_factory=list)

    def temperature_for(self, *, model: str | None, prompt_version: str | None) -> float:
        """按 model + prompt_version 精确匹配；缺切片回退默认温度并记 warning。"""
        if model:
            for item in self.params.slices:
                if item.model == model and (
                    prompt_version is None or item.prompt_version == prompt_version
                ):
                    return item.temperature
        self.warnings.append(
            f"缺少校准参数切片（model={model!r}, prompt_version={prompt_version!r}），"
            f"使用默认温度 {self.params.default_temperature}"
        )
        return self.params.default_temperature

    def calibrate(
        self, confidence: float, *, model: str | None = None, prompt_version: str | None = None
    ) -> float:
        """温度缩放置信（恒等温度直接返回原值）。"""
        temperature = self.temperature_for(model=model, prompt_version=prompt_version)
        if temperature == 1.0:
            return round(min(max(confidence, 0.0), 1.0), 6)
        return temperature_scale(confidence, temperature)


def _clamp(probability: float) -> float:
    return min(max(float(probability), _EPS), 1.0 - _EPS)


def logit(probability: float) -> float:
    """logit 变换（概率先截断到 (eps, 1-eps)，避免 ±inf）。"""
    p = _clamp(probability)
    return math.log(p / (1.0 - p))


def sigmoid(value: float) -> float:
    """数值稳定的 sigmoid。"""
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def temperature_scale(confidence: float, temperature: float) -> float:
    """温度缩放：``sigmoid(logit(p) / T)``；``T=1`` 恒等，``T≤0`` 视为非法。"""
    if temperature <= 0:
        raise ValueError("temperature 必须 > 0")
    if temperature == 1.0:
        return round(min(max(float(confidence), 0.0), 1.0), 6)
    return round(sigmoid(logit(confidence) / temperature), 6)


def fit_temperature(
    confidences: list[float],
    outcomes: list[bool],
    *,
    grid: tuple[float, ...] = DEFAULT_GRID,
    bins: int = 10,
    min_samples: int | None = None,
) -> float:
    """一维网格搜索最优温度（目标：缩放后 ECE 最小；同分取更接近 1.0）。

    空样本、全同类样本（无置信-正确性区分度）或样本量低于 ``min_samples``
    （默认 ``MIN_CALIBRATION_SAMPLES``）时返回恒等温度 1.0（由调用方标注参考值）。
    交叉验证按折调用时应传更低的 ``min_samples``（每折训练样本天然更少）。
    """
    if len(confidences) != len(outcomes):
        raise ValueError("confidences 与 outcomes 长度必须一致")
    if not confidences or len(set(outcomes)) < 2:
        return 1.0
    threshold = MIN_CALIBRATION_SAMPLES if min_samples is None else min_samples
    if len(confidences) < threshold:
        return 1.0

    best_temperature = 1.0
    best_key: tuple[float, float] | None = None
    for temperature in grid:
        scaled = [temperature_scale(c, temperature) for c in confidences]
        ece, _, _ = expected_calibration_error(scaled, outcomes, bins=bins)
        key = (round(ece, 9), abs(temperature - 1.0))
        if best_key is None or key < best_key:
            best_key = key
            best_temperature = temperature
    return round(best_temperature, 2)


def load_calibration(path: str | Path | None = None) -> CalibrationParams:
    """读取参数文件；缺失 / 空文件 / 非法结构均回退默认参数（不抛异常）。"""
    p = Path(path) if path is not None else _DEFAULT_PATH
    if not p.exists():
        return CalibrationParams()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return CalibrationParams()
    if not isinstance(data, dict):
        return CalibrationParams()
    default_temperature = _valid_temperature(data.get("default_temperature"), fallback=1.0)
    slices: list[CalibrationSlice] = []
    raw_slices = data.get("slices") or []
    if isinstance(raw_slices, list):
        for item in raw_slices:
            if not isinstance(item, dict):
                continue
            model = item.get("model")
            prompt_version = item.get("prompt_version")
            if not isinstance(model, str) or not isinstance(prompt_version, str):
                continue
            slices.append(
                CalibrationSlice(
                    model=model,
                    prompt_version=prompt_version,
                    temperature=_valid_temperature(item.get("temperature"), fallback=1.0),
                    sample_count=int(item.get("sample_count") or 0),
                )
            )
    return CalibrationParams(
        default_temperature=default_temperature,
        slices=tuple(sorted(slices, key=lambda s: (s.model, s.prompt_version))),
    )


def save_calibration(params: CalibrationParams, path: str | Path | None = None) -> None:
    """写参数文件（切片排序 + 温度两位小数；重复写入结果字节级一致）。"""
    p = Path(path) if path is not None else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "default_temperature": round(params.default_temperature, 2),
        "slices": [
            {
                "model": item.model,
                "prompt_version": item.prompt_version,
                "temperature": round(item.temperature, 2),
                "sample_count": item.sample_count,
            }
            for item in sorted(params.slices, key=lambda s: (s.model, s.prompt_version))
        ],
    }
    p.write_text(
        "# P8 置信度校准参数（温度缩放；按 model + prompt_version 切片）\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _valid_temperature(value: object, *, fallback: float) -> float:
    try:
        temperature = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return temperature if temperature > 0 else fallback


@lru_cache(maxsize=1)
def default_calibrator() -> Calibrator:
    """进程内默认校准器（读取 config/calibration.yaml；测试可 clear 缓存）。"""
    return Calibrator(params=load_calibration())
