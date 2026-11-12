/** The API's password rules (same for sign-up, reset and change). */
export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_BYTES = 72;

/** A message describing why `password` is not acceptable, or null when it is. */
export function passwordProblem(password: string): string | null {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return `Use at least ${PASSWORD_MIN_LENGTH} characters.`;
  }
  if (new TextEncoder().encode(password).length > PASSWORD_MAX_BYTES) {
    return `Passwords can be at most ${PASSWORD_MAX_BYTES} bytes long. Try a shorter one.`;
  }
  return null;
}
