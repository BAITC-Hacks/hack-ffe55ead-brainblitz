# Akim for 5 Hours

An AI-powered city budget management simulator for the Astana Innovations special track.

> Project status: MVP planning and early implementation. This README will be updated as development progresses.

## MVP Goal

Every user receives a fixed virtual budget of `100` units and must select exactly five city initiatives. The simulator validates the selected scenario, calculates its impact on city districts, and produces an **Astana Quality of Life Score**. AI explains the strengths, risks, and trade-offs of the scenario, but does not perform the numerical calculations.

## Main User Flow

1. Display the initial state of five districts and the baseline Score.
2. Let the user select five initiatives and assign districts where required.
3. Show the used and remaining budget in real time.
4. Prevent budget overruns, duplicate initiatives, and incompatible choices.
5. Calculate the new Score and changes in city indicators.
6. Display a short AI-generated explanation of the result.

## First Milestone: Working Foundation

The first priority is to build a calculation engine that works without the frontend or AI.

- [ ] Create the project structure and `.gitignore`.
- [ ] Store districts and their initial indicators in `districts.json`.
- [ ] Store initiatives, effects, implementation lags, synergies, and conflicts in `measures.json`.
- [ ] Define input and output models with Pydantic.
- [ ] Implement validation for selected initiatives.
- [ ] Implement a pure Python function for indicator and Score calculation.
- [ ] Verify the baseline Score: expected value `52.56`.
- [ ] Verify the reference scenario from the task: expected value approximately `56.54`.
- [ ] Add the minimum required endpoints: `GET /config` and `POST /simulate`.

### Definition of Done for the First Milestone

- `GET /config` returns the budget, districts, indicators, and available initiatives.
- `POST /simulate` accepts exactly five selected initiatives.
- An invalid scenario returns a clear validation error.
- A valid scenario returns the baseline and final Scores, total cost, and district-level changes.
- Repeated runs with identical input always produce identical results.

## Planned Project Structure

```text
app/
  main.py          # FastAPI application and endpoints
  models.py        # Pydantic models
  validator.py     # scenario validation rules
  simulation.py    # deterministic Score calculation
  ai.py            # AI analysis and fallback response
data/
  districts.json
  measures.json
static/
  index.html
  styles.css
  app.js
tests/
  test_simulation.py
README.md
requirements.txt
```

## Core Simulation Rules

- The total budget is `100` virtual units.
- The user must select exactly five initiatives.
- Each initiative can be selected only once.
- A district must be provided for district-level initiatives.
- A district must not be provided for city-wide initiatives.
- No more than two initiatives may come from the same category.
- Incompatible initiatives must be rejected by the validator.
- The order of the selected initiatives does not affect the result.
- All indicator values are limited to the range from `0` to `100`.

## Next Milestones

After the calculation engine is ready:

1. Build a single-screen interface for initiative selection and budget tracking.
2. Connect the interface to `/config` and `/simulate`.
3. Add a visual comparison of indicators before and after the simulation.
4. Add AI-generated explanations based on the calculated result.
5. Add a fallback explanation for cases where the AI API is unavailable.
6. Verify the complete setup process and prepare a short demonstration.

## Key Architecture Decision

The Score, budget rules, conflicts, synergies, and initiative effects are calculated only by deterministic Python code. AI receives the completed calculation and is used to explain the result and suggest improvements. This keeps the simulator reproducible even when the AI API is unavailable.



authors:
Abdulla & Nurasyl & Nurdaulet