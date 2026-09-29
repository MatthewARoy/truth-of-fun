/** Only same-origin absolute paths may be used for post-login navigation. */
export function safeReturnPath(value: string | null): string {
  if (!value?.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u0020]/.test(value)) {
    return "/explore";
  }
  const url = new URL(value, "https://local.invalid");
  if (url.origin !== "https://local.invalid" || url.pathname === "/login") return "/explore";
  return `${url.pathname}${url.search}${url.hash}`;
}
