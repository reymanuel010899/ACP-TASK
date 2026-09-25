// vitest-axe ships its augmentation against the legacy `Vi` global namespace,
// which Vitest 4 no longer reads, so `expect(...).toHaveNoViolations()` type-
// checks as missing even though `expect.extend` registers it at runtime.
// The shape mirrors @testing-library/jest-dom's own augmentation so both merge
// into one `Assertion` rather than one replacing the other.
import "vitest";
import type { AxeMatchers } from "vitest-axe/matchers";

declare module "vitest" {
  // `T` is unused here but must stay: declaration merging requires an
  // identical parameter list to jest-dom's own `Assertion<T = any>`.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-empty-object-type, @typescript-eslint/no-unused-vars
  interface Assertion<T = any> extends AxeMatchers {}
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}
