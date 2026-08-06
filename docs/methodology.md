# Methodology

Claim Harness evaluates whether the evidence behind a pull request is adequate for the claims the pull request makes. The intended unit is not a file, line, or test count. The intended unit is a claim-evidence relationship that a reviewer can inspect.

The working frame is:

```text
change claim -> evidence chain -> counterfactual probe -> mock boundary -> adequacy findings
```

## Claim Extraction

A change claim is a specific statement about behavior the PR is expected to alter or preserve. Claims may come from an issue, task description, PR body, commit message, code diff, or test name.

Examples:

- Empty passwords should return HTTP 400 instead of creating an account.
- Invalid cache metadata should fall back to a cold read.
- The retry loop should stop after the configured maximum.

Claim extraction should keep claims narrow enough to attach evidence. A broad statement such as "improve auth validation" is less useful than "empty passwords return 400 and do not create a user."

## Evidence Chain

An evidence chain links a claim to the artifacts that support it:

- The code diff that implements the claimed behavior.
- The test diff or existing tests that exercise it.
- Assertions that constrain the expected outcome.
- Coverage spans showing which changed code ran.
- CI logs showing which test commands ran.

Coverage is necessary evidence in many cases, but it is not sufficient. A line can be covered by a test that only checks that a result exists, never that the intended behavior occurred.

## Coverage Mapping

Coverage mapping asks which changed lines and branches were executed by tests that are relevant to the claim. It helps identify `Uncovered Changed Lines`, but it should not be treated as the final adequacy signal.

Useful coverage questions include:

- Did the changed branch execute at all?
- Was it executed by a test related to the issue claim?
- Did the test assert the behavior the branch is supposed to enforce?
- Did CI run the relevant test target, or only a narrowed subset?

## Counterfactual Probe

A counterfactual probe weakens, removes, or alters the claimed behavior and checks whether the attached tests fail. If tests still pass, the claim may have a `Counterfactual Survivor` finding.

Example:

An issue says empty passwords must return HTTP 400. The PR adds an empty-password branch, and a test executes the branch, but the only assertion is `result is not None`. Coverage says the new branch ran. If a probe removes the empty-password branch and the test still passes, the test did not actually constrain the 400 behavior.

That case is both a `Weak Assertion` and a `Counterfactual Survivor`: the code was covered, but the evidence did not support the claim.

## Mock Boundary Analysis

Mock boundary analysis asks whether a test replaces the core behavior it is supposed to validate. Mocks are not inherently bad; they become evidence problems when they bypass the behavior named in the claim.

Examples:

- A PR claims to fix payment retry behavior, but the test mocks the retry loop itself.
- A PR claims to harden parser error handling, but the test mocks the parser output.
- A PR claims a fallback path works, but the test mocks the failing dependency and never asserts the fallback result.

The key question is whether the mocked boundary still leaves a meaningful behavior path under test.

## Adequacy Findings

Findings should be concrete and reviewable. They should point to the claim, the evidence considered, and the reason the evidence is missing, weak, mismatched, or relatively complete.

`Evidence Complete` is deliberately modest. It means the current evidence chain appears adequate for the stated claim under the harness checks. It does not mean the implementation is correct, secure, performant, or ready to merge without human review.
