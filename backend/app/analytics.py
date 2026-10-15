def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def calculate_oee(
    operating_minutes: float,
    planned_minutes: float,
    ideal_output_seconds: float,
    good_count: float,
    total_count: float,
) -> dict[str, float]:
    availability = _ratio(operating_minutes, planned_minutes)
    performance = _ratio(ideal_output_seconds, operating_minutes * 60)
    quality = _ratio(good_count, total_count)
    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": availability * performance * quality,
    }


def calculate_defect_rate(defects: float, produced: float) -> float:
    return _ratio(defects, produced)


def evaluate_threshold(
    observed: float,
    warning: float,
    critical: float,
    comparison: str,
) -> tuple[str, float] | None:
    if comparison == "below":
        if observed >= warning:
            return None
        return ("critical", critical) if observed < critical else ("warning", warning)
    if observed <= warning:
        return None
    return ("critical", critical) if observed > critical else ("warning", warning)