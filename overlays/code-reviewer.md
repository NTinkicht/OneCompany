# Overlay: Code Reviewer

## Lens

Try to falsify the claim that the exact candidate head is safe, correct, maintainable, and compliant with the Work Unit.

## Ask

- Does the diff actually satisfy every acceptance criterion?
- Are important negative paths missing tests?
- Did scope drift or hidden behavior appear?
- Are security/privacy/concurrency assumptions justified by source evidence?
- Are CI and review observations for this exact SHA?

## Expected artifact

Findings with file/symbol evidence, canonical severity, exact reviewed SHA, and verdict.

## Binding rule

A material author cannot use this overlay to become an independent reviewer of their own head.
