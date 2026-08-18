# Normalized PR Bundle Example

This synthetic bundle demonstrates the current normalized real-PR input shape used while PR Test Guard moves toward a direct CLI and GitHub Action integration.

It does not represent a real repository, a real pull request, or scored validation data.

The bundle contains:

- PR metadata and a git-style diff;
- a small CI summary;
- optional structured change-intent candidates retained from the original prototype;
- an explicit list of evidence artifacts that are unavailable.

The example is intentionally provider-neutral at the analysis layer. A future GitHub Action should collect equivalent information from the pull-request event and local checkout, then invoke the same core logic used by the CLI.

Validate it with:

```bash
python3 -m pr_test_guard validate-real-pr-bundles
```

Missing artifacts are recorded instead of guessed. For example, if no coverage report exists, PR Test Guard should say that changed-line coverage was not evaluated rather than treating the lines as uncovered.
