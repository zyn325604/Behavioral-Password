from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


FEATURE_NAMES = [
    "duration",
    "avg_dwell",
    "std_dwell",
    "avg_flight",
    "std_flight",
    "max_flight",
    "typing_speed",
    "correction_rate",
    "pause_rate",
]

FEATURE_FLOORS = {
    "duration": 0.18,
    "avg_dwell": 0.015,
    "std_dwell": 0.010,
    "avg_flight": 0.020,
    "std_flight": 0.010,
    "max_flight": 0.040,
    "typing_speed": 0.18,
    "correction_rate": 0.050,
    "pause_rate": 0.050,
}

FEATURE_WEIGHTS = {
    "duration": 1.10,
    "avg_dwell": 1.20,
    "std_dwell": 0.90,
    "avg_flight": 1.20,
    "std_flight": 0.90,
    "max_flight": 1.00,
    "typing_speed": 1.10,
    "correction_rate": 0.80,
    "pause_rate": 0.80,
}

FEATURE_LABELS = {
    "duration": "总输入时长",
    "avg_dwell": "平均按键按下时长",
    "std_dwell": "按键时长波动",
    "avg_flight": "平均相邻击键间隔",
    "std_flight": "击键间隔波动",
    "max_flight": "最长停顿间隔",
    "typing_speed": "击键速度",
    "correction_rate": "纠错比例",
    "pause_rate": "暂停比例",
}

DEFAULT_STORAGE = Path(__file__).resolve().parent / "data" / "profiles.json"
HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 200_000
SALT_BYTES = 16


def _safe_mean(values: Iterable[float], fallback: float = 0.0) -> float:
    values = list(values)
    return statistics.fmean(values) if values else fallback


def _safe_std(values: Iterable[float], fallback: float = 0.0) -> float:
    values = list(values)
    if len(values) < 2:
        return fallback
    return statistics.pstdev(values)


@dataclass
class SampleSummary:
    final_text: str
    printable_chars: int
    total_keys: int
    correction_count: int
    duration: float
    avg_dwell: float
    std_dwell: float
    avg_flight: float
    std_flight: float
    max_flight: float
    typing_speed: float
    correction_rate: float
    pause_rate: float

    def feature_map(self) -> Dict[str, float]:
        return {name: getattr(self, name) for name in FEATURE_NAMES}

    def to_dict(self) -> Dict[str, float | int | str]:
        return asdict(self)

    def to_storage_dict(self) -> Dict[str, float | int | str]:
        data = asdict(self)
        data.pop("final_text", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, float | int | str]) -> "SampleSummary":
        payload = dict(data)
        payload.setdefault("final_text", "")
        return cls(**payload)


def finalize_sample(
    final_text: str,
    dwell_times: List[float],
    flight_times: List[float],
    correction_count: int,
    started_at: float | None,
    ended_at: float | None,
) -> SampleSummary:
    printable_chars = sum(1 for ch in final_text if ch.isprintable())
    duration = max((ended_at or 0.0) - (started_at or 0.0), 0.01)
    total_keys = len(dwell_times) + correction_count
    pauses = sum(1 for gap in flight_times if gap >= 0.70)

    avg_dwell = _safe_mean(dwell_times, 0.0)
    std_dwell = _safe_std(dwell_times, 0.0)
    avg_flight = _safe_mean(flight_times, 0.0)
    std_flight = _safe_std(flight_times, 0.0)
    max_flight = max(flight_times) if flight_times else 0.0
    typing_speed = printable_chars / duration if duration > 0 else 0.0
    correction_rate = correction_count / max(total_keys, 1)
    pause_rate = pauses / max(len(flight_times), 1)

    return SampleSummary(
        final_text=final_text,
        printable_chars=printable_chars,
        total_keys=total_keys,
        correction_count=correction_count,
        duration=duration,
        avg_dwell=avg_dwell,
        std_dwell=std_dwell,
        avg_flight=avg_flight,
        std_flight=std_flight,
        max_flight=max_flight,
        typing_speed=typing_speed,
        correction_rate=correction_rate,
        pause_rate=pause_rate,
    )


def build_template(samples: List[SampleSummary]) -> Dict[str, object]:
    if len(samples) < 3:
        raise ValueError("At least three samples are required to build a template.")

    mean_map = {
        name: _safe_mean(sample.feature_map()[name] for sample in samples)
        for name in FEATURE_NAMES
    }
    std_map = {
        name: max(_safe_std(sample.feature_map()[name] for sample in samples), FEATURE_FLOORS[name])
        for name in FEATURE_NAMES
    }

    base_template = {
        "mean": mean_map,
        "std": std_map,
        "sample_count": len(samples),
    }

    distances = [compute_distance(sample, base_template)[0] for sample in samples]
    mean_distance = _safe_mean(distances, 0.0)
    std_distance = _safe_std(distances, 0.0)
    threshold = max(1.55, mean_distance + 3.0 * std_distance, max(distances, default=1.55) + 0.12)
    threshold = min(threshold, 2.60)

    return {
        **base_template,
        "threshold": round(threshold, 3),
        "calibration": {
            "mean_distance": round(mean_distance, 3),
            "max_distance": round(max(distances, default=0.0), 3),
        },
    }


def compute_distance(
    sample: SampleSummary | Dict[str, float],
    template: Dict[str, object],
) -> Tuple[float, List[Dict[str, float | str]]]:
    feature_map = sample.feature_map() if isinstance(sample, SampleSummary) else sample
    mean_map = template["mean"]
    std_map = template["std"]
    total = 0.0
    total_weight = 0.0
    detail_rows = []

    for name in FEATURE_NAMES:
        mean_value = float(mean_map[name])
        std_value = max(float(std_map[name]), FEATURE_FLOORS[name])
        current_value = float(feature_map[name])
        deviation = abs(current_value - mean_value) / std_value
        weight = FEATURE_WEIGHTS[name]
        total += deviation * weight
        total_weight += weight
        detail_rows.append(
            {
                "name": name,
                "label": FEATURE_LABELS[name],
                "value": current_value,
                "mean": mean_value,
                "std": std_value,
                "z": deviation,
            }
        )

    detail_rows.sort(key=lambda row: row["z"], reverse=True)
    return total / max(total_weight, 1e-6), detail_rows


def evaluate_sample(sample: SampleSummary, template: Dict[str, object]) -> Dict[str, object]:
    distance, details = compute_distance(sample, template)
    threshold = float(template["threshold"])
    accepted = distance <= threshold
    score = max(0.0, min(100.0, 100.0 - (distance / max(threshold, 1e-6)) * 42.0))
    return {
        "accepted": accepted,
        "distance": round(distance, 3),
        "threshold": round(threshold, 3),
        "score": round(score, 1),
        "top_deviations": details[:3],
    }


def format_explanation(result: Dict[str, object]) -> str:
    verdict = "通过" if result["accepted"] else "未通过"
    parts = [f"鉴别结果：{verdict}。"]
    parts.append(f"综合偏差值 {result['distance']}，阈值 {result['threshold']}，匹配分数 {result['score']}。")

    deviations = result.get("top_deviations", [])
    if deviations:
        readable = "、".join(
            f"{item['label']}偏差较大(z={item['z']:.2f})"
            for item in deviations
        )
        parts.append(f"主要差异出现在：{readable}。")
    return " ".join(parts)


def ensure_storage(storage_path: Path = DEFAULT_STORAGE) -> Path:
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    if not storage_path.exists():
        storage_path.write_text(json.dumps({"profiles": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
    return storage_path


def load_profiles(storage_path: Path = DEFAULT_STORAGE) -> Dict[str, object]:
    storage_path = ensure_storage(storage_path)
    with storage_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_profiles(payload: Dict[str, object], storage_path: Path = DEFAULT_STORAGE) -> None:
    storage_path = ensure_storage(storage_path)
    with storage_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def hash_phrase(phrase: str, salt_hex: str | None = None) -> Dict[str, object]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        phrase.encode("utf-8"),
        salt,
        HASH_ITERATIONS,
    )
    return {
        "algorithm": HASH_ALGORITHM,
        "iterations": HASH_ITERATIONS,
        "salt": salt.hex(),
        "phrase_hash": digest.hex(),
    }


def verify_phrase(phrase: str, profile: Dict[str, object]) -> bool:
    if "phrase_hash" not in profile:
        return hmac.compare_digest(phrase, str(profile.get("phrase", "")))
    calculated = hash_phrase(phrase, str(profile["salt"]))["phrase_hash"]
    return hmac.compare_digest(str(profile["phrase_hash"]), str(calculated))


def _remove_plaintext_sample_fields(samples: object) -> object:
    if not isinstance(samples, list):
        return samples
    cleaned = []
    for sample in samples:
        if isinstance(sample, dict):
            item = dict(sample)
            item.pop("final_text", None)
            cleaned.append(item)
        else:
            cleaned.append(sample)
    return cleaned


def migrate_plaintext_profiles(storage_path: Path = DEFAULT_STORAGE) -> bool:
    payload = load_profiles(storage_path)
    profiles = payload.setdefault("profiles", {})
    changed = False

    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue

        phrase = profile.get("phrase")
        if isinstance(phrase, str):
            profile.update(hash_phrase(phrase))
            profile["phrase_length"] = len(phrase)
            profile.pop("phrase", None)
            changed = True

        original_samples = profile.get("samples", [])
        cleaned_samples = _remove_plaintext_sample_fields(original_samples)
        if cleaned_samples != original_samples:
            profile["samples"] = cleaned_samples
            changed = True

    if changed:
        save_profiles(payload, storage_path)
    return changed


def upsert_profile(
    username: str,
    phrase: str,
    samples: List[SampleSummary],
    storage_path: Path = DEFAULT_STORAGE,
) -> Dict[str, object]:
    payload = load_profiles(storage_path)
    template = build_template(samples)
    payload.setdefault("profiles", {})
    payload["profiles"][username] = {
        **hash_phrase(phrase),
        "phrase_length": len(phrase),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "samples": [sample.to_storage_dict() for sample in samples],
        "template": template,
    }
    save_profiles(payload, storage_path)
    return payload["profiles"][username]


def delete_profile(username: str, storage_path: Path = DEFAULT_STORAGE) -> bool:
    payload = load_profiles(storage_path)
    profiles = payload.setdefault("profiles", {})
    if username not in profiles:
        return False
    profiles.pop(username)
    save_profiles(payload, storage_path)
    return True


def get_profile(username: str, storage_path: Path = DEFAULT_STORAGE) -> Dict[str, object] | None:
    payload = load_profiles(storage_path)
    return payload.get("profiles", {}).get(username)


def list_usernames(storage_path: Path = DEFAULT_STORAGE) -> List[str]:
    payload = load_profiles(storage_path)
    return sorted(payload.get("profiles", {}).keys())


def cosine_similarity(sample: SampleSummary, template: Dict[str, object]) -> float:
    sample_values = [sample.feature_map()[name] for name in FEATURE_NAMES]
    mean_values = [float(template["mean"][name]) for name in FEATURE_NAMES]
    dot_product = sum(a * b for a, b in zip(sample_values, mean_values))
    sample_norm = math.sqrt(sum(a * a for a in sample_values))
    mean_norm = math.sqrt(sum(b * b for b in mean_values))
    if sample_norm == 0 or mean_norm == 0:
        return 0.0
    return dot_product / (sample_norm * mean_norm)
