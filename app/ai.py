from app.models import SimulationResponse


def explain_result(result: SimulationResponse) -> str:
    """Deterministic fallback until an external AI provider is configured."""
    delta = round(result.final_score - result.baseline_score, 2)
    direction = "improves" if delta >= 0 else "reduces"
    return (
        f"This scenario {direction} the city score by {abs(delta):.2f} points "
        f"and leaves {result.remaining_budget} budget units."
    )
