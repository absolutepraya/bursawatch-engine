const FORBIDDEN_PATTERNS = [
  /\b(buy|sell|hold)\b/i,
  /\btarget price\b/i,
  /\bstop[ -]?loss\b/i,
  /\bguaranteed\b/i,
  /\bget rich\b/i,
  /\bportfolio weight\b/i,
  /\bexpected return\b/i,
];

export function assertInformationOnly(text: string) {
  const violation = FORBIDDEN_PATTERNS.find((pattern) => pattern.test(text));
  if (violation) {
    throw new Error(`Unsafe investment-language pattern: ${violation.source}`);
  }
  return text;
}

export const INFORMATION_ONLY_DISCLAIMER =
  "Informasi, bukan rekomendasi investasi. Periksa sumber dan sesuaikan dengan risikomu.";
