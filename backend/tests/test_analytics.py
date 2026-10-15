import unittest

from app.analytics import calculate_defect_rate, calculate_oee, evaluate_threshold


class AnalyticsTests(unittest.TestCase):
    def test_oee_uses_aggregated_components(self) -> None:
        result = calculate_oee(
            operating_minutes=450,
            planned_minutes=500,
            ideal_output_seconds=21_600,
            good_count=950,
            total_count=1_000,
        )

        self.assertAlmostEqual(result["availability"], 0.9)
        self.assertAlmostEqual(result["performance"], 0.8)
        self.assertAlmostEqual(result["quality"], 0.95)
        self.assertAlmostEqual(result["oee"], 0.684)

    def test_oee_returns_zero_for_empty_denominators(self) -> None:
        result = calculate_oee(0, 0, 0, 0, 0)

        self.assertEqual(result, {
            "availability": 0.0,
            "performance": 0.0,
            "quality": 0.0,
            "oee": 0.0,
        })

    def test_defect_rate(self) -> None:
        self.assertAlmostEqual(calculate_defect_rate(25, 1_000), 0.025)
        self.assertEqual(calculate_defect_rate(25, 0), 0.0)

    def test_threshold_severity_and_boundaries(self) -> None:
        self.assertIsNone(evaluate_threshold(0.75, 0.75, 0.60, "below"))
        self.assertEqual(evaluate_threshold(0.70, 0.75, 0.60, "below"), ("warning", 0.75))
        self.assertEqual(evaluate_threshold(0.59, 0.75, 0.60, "below"), ("critical", 0.60))
        self.assertEqual(evaluate_threshold(0.04, 0.04, 0.08, "above"), None)
        self.assertEqual(evaluate_threshold(0.05, 0.04, 0.08, "above"), ("warning", 0.04))
        self.assertEqual(evaluate_threshold(0.09, 0.04, 0.08, "above"), ("critical", 0.08))


if __name__ == "__main__":
    unittest.main()