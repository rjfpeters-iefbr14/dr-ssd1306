# Contributing

Install the project and its test tools with `uv sync`.
Run `uv run pytest -q` before submitting a change.
Build the wheel and source distribution with `uv build`.
Commit `uv.lock` after intentional dependency changes; use `uv lock --upgrade`
to update dependency versions and rerun the tests.
Use a fake clock and fake display in tests; CI has no Raspberry Pi hardware.
Keep the physical framebuffer one-bit and exactly 128 × 64 pixels.
Keep real equipment integration separate from simulation and label the data source.
Record an implementation decision in `docs/decisions/` (copy `template.md`).
Describe the behavior changed and relevant test results in your pull request.
Do not commit settings files containing private configuration or passwords.
