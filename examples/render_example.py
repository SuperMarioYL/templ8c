"""Minimal templ8c programmatic example.

Run after ``pip install -e .`` from the repo root:

    python examples/render_example.py

Shows the two m1 entry points: render a single message through a model's
reference chat template, and run a full conformance check.
"""

from templ8c.checker import Checker


def main() -> None:
    checker = Checker()

    rendered = checker.render("glm-5.3-flash", "What's the weather in SF?")
    print("--- rendered prompt ---")
    print(rendered)

    result = checker.check("glm-5.3-flash")
    print("\n--- conformance check ---")
    print(f"model: {result.model_id}")
    print(f"passed: {result.passed}  ({result.failed_count} failure(s))")
    for diff in result.diffs:
        print(f"  {diff.status:4}  {diff.field}")


if __name__ == "__main__":
    main()
